"""
Analysis service: orchestrates feature extraction + model scoring.
"""
from pathlib import Path
import json
import joblib
import pandas as pd
import numpy as np
import xgboost as xgb

from app.ml.features import build_features, FEATURE_EXPLANATIONS
from app.db import update_job

MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# Feature name → display name mapping for SHAP contributions
FEATURE_DISPLAY_NAMES = {
    "aim_pitch_delta_mean": "aim_pitch_delta_mean",
    "aim_pitch_delta_std": "aim_pitch_delta_std",
    "aim_yaw_delta_mean": "aim_yaw_delta_mean",
    "aim_yaw_delta_std": "aim_yaw_delta_std",
    "aim_mouse_mag_mean": "aim_mouse_mag_mean",
    "aim_mouse_mag_std": "aim_mouse_mag_std",
    "aim_fov_changes": "aim_fov_changes",
    "aim_scope_time_ratio": "aim_scope_time_ratio",
    "combat_kdr": "combat_kdr",
    "combat_headshot_ratio": "combat_headshot_ratio",
    "combat_damage_per_round": "combat_damage_per_round",
    "combat_kills_per_round": "combat_kills_per_round",
    "combat_ace_rounds": "combat_ace_rounds",
    "combat_4k_rounds": "combat_4k_rounds",
    "combat_3k_rounds": "combat_3k_rounds",
    "combat_shots_fired": "combat_shots_fired",
    "move_vel_mean": "move_vel_mean",
    "move_vel_std": "move_vel_std",
    "move_vel_max": "move_vel_max",
    "move_airborne_ratio": "move_airborne_ratio",
    "move_duck_mean": "move_duck_mean",
    "move_walk_ratio": "move_walk_ratio",
    "move_fall_vel_max": "move_fall_vel_max",
    "btn_fire_rate": "btn_fire_rate",
    "btn_reload_rate": "btn_reload_rate",
    "btn_zoom_rate": "btn_zoom_rate",
    "json_kills": "json_kills",
    "json_headshots": "json_headshots",
    "json_wallbangs": "json_wallbangs",
    "json_headshot_ratio": "json_headshot_ratio",
}


def load_model():
    """Load trained model artifact."""
    model_path = MODELS_DIR / "model_v1.joblib"
    if not model_path.exists():
        return None
    return joblib.load(model_path)


def extract_match_info(tick_df: pd.DataFrame, events: dict, folder: str, idx: int) -> dict:
    """Infer match metadata from tick data and JSON events."""
    map_name = "Unknown"
    if "map_name" in tick_df.columns:
        map_name = tick_df["map_name"].dropna().iloc[0] if not tick_df["map_name"].dropna().empty else "Unknown"
    elif "map" in tick_df.columns:
        map_name = tick_df["map"].dropna().iloc[0] if not tick_df["map"].dropna().empty else "Unknown"

    rounds = 0
    if "gameRounds" in events:
        rounds = len(events["gameRounds"])
    elif "round_freeze_end" in events:
        rounds = len(events["round_freeze_end"])
    elif "round" in tick_df.columns:
        rounds = int(tick_df["round"].nunique())

    duration_ticks = len(tick_df)
    score = "?"
    game_rounds = events.get("gameRounds", [])
    if game_rounds and isinstance(game_rounds, list) and game_rounds:
        last = game_rounds[-1]
        if isinstance(last, dict):
            t_score = last.get("tScore")
            ct_score = last.get("ctScore")
            if t_score is not None and ct_score is not None:
                score = f"{t_score}:{ct_score}"

    cheaters = events.get("cheaters", [])
    cheat_names = [c.get("steamid", "?") for c in cheaters]
    narrative = f"Матч из датасета #{idx} ({folder}). Карта: {map_name}, раундов: {rounds}."
    if cheat_names:
        narrative += f" Известные читеры: {', '.join(cheat_names)}."
    else:
        narrative += " Чистый матч (читеры не обнаружены в разметке)."

    return {
        "map_name": map_name,
        "rounds": rounds,
        "duration_ticks": duration_ticks,
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
    
    # Player deaths
    deaths = events.get("player_death", [])
    for d in deaths[:50]:  # Limit to first 50 events
        attacker = d.get("attacker_steamid", "?")
        victim = d.get("user_steamid", "?")
        weapon = d.get("weapon", "?")
        headshot = d.get("headshot", False)
        tick = d.get("tick", 0)
        
        # Convert tick to mm:ss.hh time format (hundredths of a second)
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
            "type": "headshot" if headshot else "kill"
        })
        last_tick = max(last_tick, tick)
    
    # Round events
    round_events = events.get("round_freeze_end", [])
    for i, r in enumerate(round_events[:30]):
        tick = r.get("tick", 0) if isinstance(r, dict) else 0
        # Convert tick to mm:ss.hh time format (hundredths of a second)
        seconds = tick // 64
        minutes = seconds // 60
        sec_part = seconds % 60
        hundredths = (tick % 64) * 100 // 64
        time_str = f"{minutes}:{sec_part:02d}.{hundredths:02d}"
        
        match_events.append({
            "tick": tick,
            "time": time_str,
            "description": f"Раунд {i+1} начался",
            "type": "round"
        })
        last_tick = max(last_tick, tick)
    
    # Sort by tick
    match_events.sort(key=lambda x: x["tick"])
    
    # Add logarithmic separators between events
    result = []
    for i, event in enumerate(match_events):
        if i > 0:
            tick_diff = event["tick"] - match_events[i-1]["tick"]
            if tick_diff > 0:
                # Logarithmic scaling based on seconds: ~0s -> 1px, 1s -> 3px, 2s -> 5px, etc.
                import math
                seconds = tick_diff / 64.0
                height = max(1, min(40, 1 + round(math.log10(seconds + 1) * 8)))
                result.append({
                    "tick": event["tick"],
                    "time": "",
                    "description": "",
                    "type": "separator",
                    "height": height
                })
        result.append(event)
    
    return result[:100]  # Limit total events


def get_shap_contributions(row: pd.Series, feature_names: list, scaler, booster, n: int = 5) -> dict:
    """Compute per-feature SHAP-like contributions for a single player using XGBoost pred_contribs."""
    try:
        # Build single-row matrix
        x = np.array([[float(row.get(f, 0.0)) for f in feature_names]])
        x = np.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6)
        x_scaled = scaler.transform(x)
        dm = xgb.DMatrix(x_scaled, feature_names=feature_names)
        contribs = booster.predict(dm, pred_contribs=True)[0]  # shape: (n_features + 1,)

        # Last element is the bias/intercept
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

        # Sort by absolute contribution
        feature_contribs.sort(key=lambda x: x["abs_value"], reverse=True)

        # Filter: only show contributions >= 0.1, round to 3 decimals
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

        return {
            "bias": round(bias, 3),
            "positive": pos,
            "negative": neg,
        }
    except Exception:
        return {"bias": 0, "positive": [], "negative": []}


def get_top_factors(row: pd.Series, feature_names: list, explanations: dict, n: int = 3) -> list:
    """Get top contributing factor patterns (combinations) for a player's risk score."""
    patterns = []

    def safe_get(key, default=0):
        if key in row.index:
            v = row[key]
            return float(v) if pd.notna(v) else default
        return default

    kdr = safe_get("combat_kdr")
    hs_ratio = safe_get("combat_headshot_ratio")
    dpr = safe_get("combat_damage_per_round")
    yaw_std = safe_get("aim_yaw_delta_std")
    mouse_mag = safe_get("aim_mouse_mag_mean")
    wallbangs = safe_get("json_wallbangs")
    fire_rate = safe_get("btn_fire_rate")
    kpr = safe_get("combat_kills_per_round")
    pitch_std = safe_get("aim_pitch_delta_std")
    vel_std = safe_get("move_vel_std")

    # Pattern 1: High KDR + high headshot ratio
    if kdr > 3 and hs_ratio > 0.6:
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Высокий KDR при высокой доле хедшотов"
        })
        patterns.append({
            "name": "combat_headshot_ratio",
            "value": f"{hs_ratio*100:.0f}%",
            "explanation": "Высокий KDR при высокой доле хедшотов"
        })

    # Pattern 2: Low mouse movement + good KDR
    if mouse_mag < 3 and kdr > 2:
        patterns.append({
            "name": "aim_mouse_mag_mean",
            "value": f"{mouse_mag:.1f}",
            "explanation": "Малая амплитуда мыши при высоком KDR"
        })
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Малая амплитуда мыши при высоком KDR"
        })

    # Pattern 3: High damage + wallbangs
    if dpr > 120 and wallbangs > 1:
        patterns.append({
            "name": "combat_damage_per_round",
            "value": f"{dpr:.0f}",
            "explanation": "Высокий урон с убийствами через стены"
        })
        patterns.append({
            "name": "json_wallbangs",
            "value": f"{int(wallbangs)}",
            "explanation": "Высокий урон с убийствами через стены"
        })

    # Pattern 4: Low yaw/pitch delta
    if yaw_std < 1.0 and pitch_std < 1.0:
        patterns.append({
            "name": "aim_yaw_delta_std",
            "value": f"{yaw_std:.2f}",
            "explanation": "Низкое отклонение углов поворота"
        })
        patterns.append({
            "name": "aim_pitch_delta_std",
            "value": f"{pitch_std:.2f}",
            "explanation": "Низкое отклонение углов поворота"
        })

    # Pattern 5: High KPR + high DPR
    if kpr > 2.0 and dpr > 150:
        patterns.append({
            "name": "combat_kills_per_round",
            "value": f"{kpr:.1f}",
            "explanation": "Высокое количество убийств и урона за раунд"
        })
        patterns.append({
            "name": "combat_damage_per_round",
            "value": f"{dpr:.0f}",
            "explanation": "Высокое количество убийств и урона за раунд"
        })

    # Pattern 6: Low velocity std + high KDR
    if vel_std < 20 and kdr > 2.5:
        patterns.append({
            "name": "move_vel_std",
            "value": f"{vel_std:.1f}",
            "explanation": "Низкий разброс скорости при высоком KDR"
        })
        patterns.append({
            "name": "combat_kdr",
            "value": f"{kdr:.1f}",
            "explanation": "Низкий разброс скорости при высоком KDR"
        })

    # Pattern 7: High fire rate + headshots
    if fire_rate > 0.15 and hs_ratio > 0.5:
        patterns.append({
            "name": "btn_fire_rate",
            "value": f"{fire_rate:.3f}",
            "explanation": "Высокая частота стрельбы с хедшотами"
        })
        patterns.append({
            "name": "combat_headshot_ratio",
            "value": f"{hs_ratio*100:.0f}%",
            "explanation": "Высокая частота стрельбы с хедшотами"
        })

    # Fallback: individual suspicious features if no patterns matched
    if not patterns:
        individual = []
        if kdr > 3:
            individual.append({"name": "combat_kdr", "value": f"{kdr:.1f}", "explanation": "KDR выше 3"})
        if hs_ratio > 0.7:
            individual.append({"name": "combat_headshot_ratio", "value": f"{hs_ratio*100:.0f}%", "explanation": "Доля хедшотов выше 70%"})
        if dpr > 150:
            individual.append({"name": "combat_damage_per_round", "value": f"{dpr:.0f}", "explanation": "Урон за раунд выше 150"})
        if yaw_std < 1.0:
            individual.append({"name": "aim_yaw_delta_std", "value": f"{yaw_std:.2f}", "explanation": "Отклонение yaw ниже 1.0"})
        if mouse_mag < 3:
            individual.append({"name": "aim_mouse_mag_mean", "value": f"{mouse_mag:.1f}", "explanation": "Амплитуда мыши ниже 3"})
        if wallbangs > 2:
            individual.append({"name": "json_wallbangs", "value": f"{int(wallbangs)}", "explanation": "Убийств через стены выше 2"})
        patterns = individual

    return patterns[:n]


def analyze_match(job_id: str, file_path: str, events: dict | None = None, match_info: dict | None = None):
    """Run analysis on a match file."""
    update_job(job_id, "processing")

    try:
        tick_df = pd.read_parquet(file_path)
        if events is None:
            events = {"cheaters": []}

        # Build features
        feats = build_features(tick_df, events, "unknown")

        # Extract match events
        match_events = extract_match_events(events)

        # Load model
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

        # Prepare features
        X = feats[feature_names].values
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        X_scaled = scaler.transform(X)

        # Predict
        proba = model.predict_proba(X_scaled)[:, 1]
        risk_scores = (proba * 100).astype(int)
        flags = proba >= threshold

        # Get XGBoost booster for SHAP contributions
        try:
            booster = model.estimator.get_booster()
        except Exception:
            booster = None

        # Build player results
        players = []
        for i, row in feats.iterrows():
            top_factors = get_top_factors(row, feature_names, FEATURE_EXPLANATIONS)
            shap = get_shap_contributions(row, feature_names, scaler, booster) if booster else {"bias": 0, "positive": [], "negative": []}
            players.append({
                "steamid": row["steamid"],
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
            }
        }
        if match_info:
            result["match_info"] = match_info

        update_job(job_id, "done", json.dumps(result, ensure_ascii=False))

    except Exception as e:
        result = {"status": "error", "message": str(e)}
        update_job(job_id, "error", json.dumps(result, ensure_ascii=False))
        raise
