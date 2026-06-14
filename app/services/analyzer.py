"""
Analysis service: orchestrates feature extraction + model scoring.
Supports both legacy model_v1.joblib and new ensemble (supervised + anomaly).
"""
from pathlib import Path
import json
import logging
import joblib
import polars as pl
import numpy as np
import xgboost as xgb

from app.ml.features import build_features, FEATURE_EXPLANATIONS
from app.db import update_job

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# Columns to read from parquet — only what build_features() + extract_match_info() need.
PARQUET_READ_COLS = [
    "steamid", "name", "tick",
    "pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy", "fov", "is_scoped",
    "kills_total", "deaths_total", "headshot_kills_total", "damage_total",
    "shots_fired", "ace_rounds_total", "4k_rounds_total", "3k_rounds_total",
    "velocity", "is_airborne", "fall_velo", "duck_amount", "is_walking",
    "FIRE", "RELOAD", "ZOOM",
    "total_rounds_played", "map_name", "round",
]

FEATURE_DISPLAY_NAMES = {
    "aim_pitch_delta_mean": "Наклон прицела (mean)",
    "aim_pitch_delta_std": "Наклон прицела (std)",
    "aim_yaw_delta_mean": "Поворот прицела (mean)",
    "aim_yaw_delta_std": "Поворот прицела (std)",
    "aim_mouse_mag_mean": "Амплитуда мыши (mean)",
    "aim_mouse_mag_std": "Амплитуда мыши (std)",
    "aim_fov_changes": "Изменения FOV",
    "aim_scope_time_ratio": "Доля времени в оптике",
    "combat_kdr": "KDR",
    "combat_headshot_ratio": "Доля хедшотов",
    "move_vel_mean": "Скорость (mean)",
    "move_vel_std": "Скорость (std)",
    "move_vel_max": "Скорость (max)",
    "move_airborne_ratio": "Доля времени в воздухе",
    "move_duck_mean": "Доля приседаний",
    "move_walk_ratio": "Доля ходьбы",
    "btn_fire_rate": "Частота стрельбы",
    "btn_reload_rate": "Частота перезарядки",
    "btn_zoom_rate": "Частота использования оптики",
    "json_kills": "Убийства (события)",
    "json_headshots": "Хедшоты (события)",
    "json_wallbangs": "Убийства через стены",
    "json_headshot_ratio": "Доля хедшотов (события)",
}


def load_model():
    """Load trained model artifact."""
    ensemble_path = MODELS_DIR / "ensemble_config_v1.joblib"
    supervised_path = MODELS_DIR / "supervised_v1.joblib"
    iso_path = MODELS_DIR / "isolation_forest_v1.joblib"

    if ensemble_path.exists() and supervised_path.exists() and iso_path.exists():
        try:
            ensemble = joblib.load(ensemble_path)
            supervised = joblib.load(supervised_path)
            iso = joblib.load(iso_path)
            return {
                "type": "ensemble",
                "model": supervised["model"],
                "scaler": ensemble["scaler"],
                "feature_names": ensemble["feature_names"],
                "threshold": ensemble["threshold"],
                "supervised_weight": ensemble["supervised_weight"],
                "anomaly_weight": ensemble["anomaly_weight"],
                "iso_model": iso["model"],
            }
        except Exception as e:
            logger.warning("Failed to load ensemble model: %s", e)

    model_path = MODELS_DIR / "model_v1.joblib"
    if model_path.exists():
        artifact = joblib.load(model_path)
        artifact["type"] = "single"
        return artifact
    return None


def extract_match_info(tick_df: pl.DataFrame, events: dict, folder: str, idx: str | int) -> dict:
    """Infer match metadata from tick data and JSON events."""
    map_name = "Unknown"
    if "map_name" in tick_df.columns:
        raw = tick_df["map_name"].drop_nulls()
        if len(raw) > 0:
            map_name = raw.to_list()[0]
            if map_name.startswith("de_"):
                map_name = map_name[3:].capitalize()
    elif "map" in tick_df.columns:
        raw = tick_df["map"].drop_nulls()
        if len(raw) > 0:
            map_name = raw.to_list()[0]

    rounds = 0
    if "gameRounds" in events:
        rounds = len(events["gameRounds"])
    elif "round_freeze_end" in events:
        rounds = len(events["round_freeze_end"])
    elif "round" in tick_df.columns:
        rounds = tick_df["round"].n_unique()

    duration_ticks = tick_df["tick"].n_unique() if "tick" in tick_df.columns else len(tick_df)
    score = "?"
    game_rounds = events.get("gameRounds", [])
    if game_rounds and isinstance(game_rounds, list) and game_rounds:
        last = game_rounds[-1]
        if isinstance(last, dict):
            t_score = last.get("tScore")
            ct_score = last.get("ctScore")
            if t_score is not None and ct_score is not None:
                score = f"{t_score}:{ct_score}"

    duration_sec = duration_ticks // 64
    duration_min = duration_sec // 60
    duration_str = f"{duration_min}:{duration_sec % 60:02d}"

    cheaters = events.get("cheaters", [])
    cheat_names = [c.get("steamid", "?") for c in cheaters]
    narrative = f"Матч из датасета #{idx} ({folder}). Карта: {map_name}, раундов: {rounds}."
    if cheat_names:
        narrative += f" Известные читеры: {', '.join(cheat_names)}."
    else:
        narrative += " Чистый матч (читеры не обнаружены в разметке)."

    return {
        "map_name": map_name,
        "map": map_name,
        "rounds": rounds,
        "duration_ticks": duration_ticks,
        "duration": duration_str,
        "score": score,
        "narrative": narrative,
        "dataset_folder": folder,
        "dataset_idx": idx,
        "known_cheaters": cheat_names,
    }


def extract_match_events(events: dict) -> list:
    """Extract important match events for display."""
    match_events = []
    last_tick = 0

    deaths = events.get("player_death", [])
    for d in deaths[:50]:
        attacker = d.get("attacker_steamid", "?")
        victim = d.get("user_steamid", "?")
        weapon = d.get("weapon", "?")
        headshot = d.get("headshot", False)
        tick = d.get("tick", 0)

        seconds = tick // 64
        minutes = seconds // 60
        sec_part = seconds % 60
        hundredths = (tick % 64) * 100 // 64
        time_str = f"{minutes}:{sec_part:02d}.{hundredths:02d}"

        desc = f"{attacker} убил {victim}"
        if weapon and weapon != "?":
            desc += f" [{weapon}]"
        if headshot:
            desc += " - хедшот"

        match_events.append({
            "tick": tick,
            "time": time_str,
            "description": desc,
            "type": "headshot" if headshot else "kill",
        })
        last_tick = max(last_tick, tick)

    round_events = events.get("round_freeze_end", [])
    for i, r in enumerate(round_events[:30]):
        tick = r.get("tick", 0) if isinstance(r, dict) else 0
        seconds = tick // 64
        minutes = seconds // 60
        sec_part = seconds % 60
        hundredths = (tick % 64) * 100 // 64
        time_str = f"{minutes}:{sec_part:02d}.{hundredths:02d}"

        match_events.append({
            "tick": tick,
            "time": time_str,
            "description": f"Раунд {i+1} начался",
            "type": "round",
        })
        last_tick = max(last_tick, tick)

    match_events.sort(key=lambda x: x["tick"])

    result = []
    for i, event in enumerate(match_events):
        if i > 0:
            tick_diff = event["tick"] - match_events[i - 1]["tick"]
            if tick_diff > 0:
                import math
                seconds = tick_diff / 64.0
                height = max(1, min(40, 1 + round(math.log10(seconds + 1) * 8)))
                result.append({
                    "tick": event["tick"],
                    "time": "",
                    "description": "",
                    "type": "separator",
                    "height": height,
                })
        result.append(event)

    return result[:100]


def get_shap_contributions(row: dict, feature_names: list, scaler, booster, n: int = 5) -> dict:
    """Compute per-feature SHAP-like contributions for a single player."""
    try:
        x = np.array([[float(row.get(f, 0.0)) for f in feature_names]])
        x = np.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6)
        x_scaled = scaler.transform(x)
        dm = xgb.DMatrix(x_scaled, feature_names=feature_names)
        contribs = booster.predict(dm, pred_contribs=True)[0]

        bias = float(contribs[-1])
        feature_contribs = []
        for i, fname in enumerate(feature_names):
            val = float(contribs[i])
            display_name = FEATURE_DISPLAY_NAMES.get(fname, fname)
            feature_contribs.append({
                "feature": display_name,
                "raw_feature": fname,
                "value": round(val, 4),
                "abs_value": abs(val),
            })

        feature_contribs.sort(key=lambda x: x["abs_value"], reverse=True)
        feature_contribs = [
            {
                "feature": c["feature"],
                "raw_feature": c["raw_feature"],
                "value": round(c["value"], 3),
                "abs_value": c["abs_value"],
            }
            for c in feature_contribs
            if abs(c["value"]) >= 0.1
        ]

        pos = [c for c in feature_contribs if c["value"] > 0][:n]
        neg = [c for c in feature_contribs if c["value"] < 0][:n]

        return {"bias": round(bias, 3), "positive": pos, "negative": neg}
    except Exception as e:
        logger.debug("SHAP contribution error: %s", e)
        return {"bias": 0, "positive": [], "negative": []}


def get_top_factors(row: dict, feature_names: list, explanations: dict, n: int = 3) -> list:
    """Get top contributing factor patterns for a player's risk score."""
    patterns = []

    def safe_get(key, default=0):
        if key in row:
            v = row[key]
            return float(v) if v is not None else default
        return default

    kdr = safe_get("combat_kdr")
    hs_ratio = safe_get("combat_headshot_ratio")
    yaw_std = safe_get("aim_yaw_delta_std")
    mouse_mag = safe_get("aim_mouse_mag_mean")
    wallbangs = safe_get("json_wallbangs")
    fire_rate = safe_get("btn_fire_rate")
    pitch_std = safe_get("aim_pitch_delta_std")
    vel_std = safe_get("move_vel_std")
    vel_mean = safe_get("move_vel_mean")

    if kdr > 3 and hs_ratio > 0.6:
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Высокий KDR при высокой доле хедшотов",
        })
        patterns.append({
            "name": "combat_headshot_ratio",
            "value": f"{hs_ratio*100:.0f}%",
            "explanation": "Высокий KDR при высокой доле хедшотов",
        })

    if mouse_mag < 3 and kdr > 2:
        patterns.append({
            "name": "aim_mouse_mag_mean",
            "value": f"{mouse_mag:.1f}",
            "explanation": "Малая амплитуда мыши при высоком KDR",
        })
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Малая амплитуда мыши при высоком KDR",
        })

    if wallbangs > 1:
        patterns.append({
            "name": "json_wallbangs",
            "value": f"{int(wallbangs)}",
            "explanation": "Убийства через стены — подозрительная активность",
        })

    if yaw_std < 1.0 and pitch_std < 1.0:
        patterns.append({
            "name": "aim_yaw_delta_std",
            "value": f"{yaw_std:.2f}",
            "explanation": "Низкое отклонение углов поворота",
        })
        patterns.append({
            "name": "aim_pitch_delta_std",
            "value": f"{pitch_std:.2f}",
            "explanation": "Низкое отклонение углов поворота",
        })

    if vel_std < 20 and kdr > 2.5:
        patterns.append({
            "name": "move_vel_std",
            "value": f"{vel_std:.1f}",
            "explanation": "Низкий разброс скорости при высоком KDR",
        })
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Низкий разброс скорости при высоком KDR",
        })

    if fire_rate > 0.15 and hs_ratio > 0.5:
        patterns.append({
            "name": "btn_fire_rate",
            "value": f"{fire_rate:.3f}",
            "explanation": "Высокая частота стрельбы с хедшотами",
        })
        patterns.append({
            "name": "combat_headshot_ratio",
            "value": f"{hs_ratio*100:.0f}%",
            "explanation": "Высокая частота стрельбы с хедшотами",
        })

    if not patterns:
        if kdr > 3:
            patterns.append({"name": "combat_kdr", "value": f"{kdr:.1f}", "explanation": "KDR выше 3"})
        if hs_ratio > 0.7:
            patterns.append({"name": "combat_headshot_ratio", "value": f"{hs_ratio*100:.0f}%", "explanation": "Доля хедшотов выше 70%"})
        if yaw_std < 1.0:
            patterns.append({"name": "aim_yaw_delta_std", "value": f"{yaw_std:.2f}", "explanation": "Отклонение yaw ниже 1.0"})
        if mouse_mag < 3:
            patterns.append({"name": "aim_mouse_mag_mean", "value": f"{mouse_mag:.1f}", "explanation": "Амплитуда мыши ниже 3"})
        if wallbangs > 2:
            patterns.append({"name": "json_wallbangs", "value": f"{int(wallbangs)}", "explanation": "Убийств через стены выше 2"})

    return patterns[:n]


def analyze_match(job_id: str, file_path: str, events: dict | None = None, match_info: dict | None = None, tick_df: pl.DataFrame | None = None):
    """Run analysis on a match file."""
    update_job(job_id, "processing")
    logger.info("analyze_match start job=%s", job_id)

    try:
        if tick_df is None:
            tick_df = pl.read_parquet(file_path, columns=PARQUET_READ_COLS)
        if events is None:
            events = {"cheaters": []}

        _needed = {"steamid", "name", "tick",
            "pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy", "fov", "is_scoped",
            "kills_total", "deaths_total", "headshot_kills_total", "damage_total",
            "shots_fired", "ace_rounds_total", "4k_rounds_total", "3k_rounds_total",
            "velocity", "is_airborne", "fall_velo", "duck_amount", "is_walking",
            "FIRE", "RELOAD", "ZOOM",
            "total_rounds_played"}
        _present = [c for c in _needed if c in tick_df.columns]
        tick_df = tick_df.select(_present)
        logger.info("analyze_match cols=%d job=%s", len(tick_df.columns), job_id)

        feats = build_features(tick_df, events, "unknown")

        name_map = {}
        if "name" in tick_df.columns and "steamid" in tick_df.columns:
            name_map = dict(zip(tick_df["steamid"].cast(str).to_list(), tick_df["name"].to_list()))
        del tick_df

        match_events = extract_match_events(events)

        artifact = load_model()
        if artifact is None:
            result = {
                "status": "done",
                "model_loaded": False,
                "players": [],
                "message": "Модель не обучена. Запустите scripts/train_subset.py.",
            }
            if match_info:
                result["match_info"] = match_info
            update_job(job_id, "done", json.dumps(result, ensure_ascii=False))
            return

        model = artifact["model"]
        scaler = artifact["scaler"]
        feature_names = artifact["feature_names"]
        threshold = artifact.get("threshold", 0.5)

        X = feats.select(feature_names).to_numpy()
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        X_scaled = scaler.transform(X)

        model_type = artifact.get("type", "single")
        if model_type == "ensemble":
            sup_proba = model.predict_proba(X_scaled)[:, 1]
            iso_model = artifact["iso_model"]
            iso_scores = iso_model.decision_function(X_scaled)
            iso_risk = (1 - (iso_scores - iso_scores.min()) / (iso_scores.max() - iso_scores.min() + 1e-8))
            w_sup = artifact["supervised_weight"]
            w_anom = artifact["anomaly_weight"]
            proba = w_sup * sup_proba + w_anom * iso_risk
        else:
            proba = model.predict_proba(X_scaled)[:, 1]

        risk_scores = (proba * 100).astype(int)
        flags = proba >= threshold

        try:
            if model_type == "ensemble":
                booster = model.estimator.get_booster()
            else:
                booster = model.estimator.get_booster()
        except Exception:
            booster = None

        players = []
        for i, row in enumerate(feats.iter_rows(named=True)):
            top_factors = get_top_factors(row, feature_names, FEATURE_EXPLANATIONS)
            shap = get_shap_contributions(row, feature_names, scaler, booster) if booster else {"bias": 0, "positive": [], "negative": []}
            sid = str(row["steamid"])
            players.append({
                "steamid": sid,
                "name": name_map.get(sid, sid),
                "risk_score": int(risk_scores[i]),
                "flagged": bool(flags[i]),
                "confidence": float(proba[i]),
                "features": {
                    "kdr": round(row.get("combat_kdr", 0), 2),
                    "headshot_ratio": round(row.get("combat_headshot_ratio", 0), 2),
                    "damage_per_round": round(row.get("combat_damage_per_round", 0), 1),
                    "aim_yaw_std": round(row.get("aim_yaw_delta_std", 0), 3),
                    "aim_pitch_std": round(row.get("aim_pitch_delta_std", 0), 3),
                    "mouse_mag_mean": round(row.get("aim_mouse_mag_mean", 0), 2),
                    "vel_mean": round(row.get("move_vel_mean", 0), 1),
                    "fire_rate": round(row.get("btn_fire_rate", 0), 4),
                    "wallbangs": int(row.get("json_wallbangs", 0)),
                },
                "top_factors": top_factors,
                "shap": shap,
            })

        players.sort(key=lambda x: x["risk_score"], reverse=True)

        result = {
            "status": "done",
            "model_loaded": True,
            "threshold": threshold,
            "players": players,
            "match_events": match_events,
            "feature_explanations": FEATURE_EXPLANATIONS,
            "summary": {
                "total_players": len(players),
                "flagged_players": int(flags.sum()),
                "avg_risk": round(float(risk_scores.mean()), 1),
                "max_risk": int(risk_scores.max()),
            },
        }
        if match_info:
            result["match_info"] = match_info

        update_job(job_id, "done", json.dumps(result, ensure_ascii=False))
        logger.info("analyze_match done job=%s players=%d flagged=%d", job_id, len(players), int(flags.sum()))

    except Exception as e:
        logger.exception("Analysis failed for job %s", job_id)
        result = {"status": "error", "message": f"Ошибка анализа: {e}"}
        update_job(job_id, "error", json.dumps(result, ensure_ascii=False))
