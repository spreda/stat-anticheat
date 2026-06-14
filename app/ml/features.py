"""
Feature engineering for CS2 anti-cheat (polars).
Transforms per-tick per-player data into player-match feature vectors.
"""
import polars as pl
import numpy as np
from pathlib import Path
import json

FEATURE_EXPLANATIONS = {
    "aim_pitch_delta_mean": "Среднее изменение угла наклона прицела между тиками.",
    "aim_pitch_delta_std": "Разброс изменений угла наклона прицела.",
    "aim_yaw_delta_mean": "Среднее изменение угла поворота между тиками.",
    "aim_yaw_delta_std": "Разброс изменений угла поворота. Характеризует плавность прицеливания.",
    "aim_mouse_mag_mean": "Средняя величина перемещения мыши.",
    "aim_mouse_mag_std": "Разброс величин перемещения мыши.",
    "aim_fov_changes": "Количество изменений поля зрения.",
    "aim_scope_time_ratio": "Доля времени в прицеливании.",
    "combat_kdr": "Соотношение убийств к смертям.",
    "combat_headshot_ratio": "Доля убийств в голову.",
    "combat_damage_per_round": "Средний урон за раунд.",
    "combat_kills_per_round": "Среднее количество убийств за раунд.",
    "combat_ace_rounds": "Количество раундов с убийством пяти противников.",
    "combat_4k_rounds": "Количество раундов с четырьмя убийствами.",
    "combat_3k_rounds": "Количество раундов с тремя убийствами.",
    "combat_shots_fired": "Общее количество выстрелов.",
    "move_vel_mean": "Средняя скорость передвижения.",
    "move_vel_std": "Разброс скорости передвижения.",
    "move_vel_max": "Максимальная зафиксированная скорость.",
    "move_airborne_ratio": "Доля времени в воздухе.",
    "move_duck_mean": "Среднее состояние приседания.",
    "move_walk_ratio": "Доля ходьбы относительно бега.",
    "move_fall_vel_max": "Максимальная скорость падения.",
    "btn_fire_rate": "Частота нажатия кнопки выстрела.",
    "btn_reload_rate": "Частота перезарядки оружия.",
    "btn_zoom_rate": "Частота использования оптического прицела.",
    "json_kills": "Количество зафиксированных убийств по данным событий матча.",
    "json_headshots": "Количество зафиксированных убийств в голову по данным событий матча.",
    "json_wallbangs": "Количество убийств через препятствия.",
    "json_headshot_ratio": "Доля убийств в голову по данным событий матча.",
}


def load_match(folder: Path, idx: int) -> tuple[pl.DataFrame, dict]:
    tick_df = pl.read_parquet(folder / f"{idx}.parquet")
    with open(folder / f"{idx}.json", "r") as f:
        events = json.load(f)
    return tick_df, events


def get_cheater_set(events: dict) -> set:
    cheaters = events.get("cheaters", [])
    return {c["steamid"] for c in cheaters}


def label_players(df: pl.DataFrame, cheater_set: set, match_folder: str) -> pl.DataFrame:
    df = df.with_columns(
        pl.col("steamid").is_in(tuple(cheater_set)).cast(pl.Int64).alias("is_cheater"),
    )
    label_conf = (
        pl.lit(0.8)
        if match_folder == "no_cheater_present"
        else pl.when(pl.col("is_cheater") == 1).then(1.0).otherwise(0.9)
    )
    return df.with_columns(label_conf.alias("label_confidence"))


def compute_aim_features(df: pl.DataFrame) -> pl.DataFrame:
    df = df.sort(["steamid", "tick"])
    df = df.with_columns(
        pl.col("pitch").diff().over("steamid").abs().alias("pitch_delta"),
        pl.col("yaw").diff().over("steamid").abs().alias("yaw_diff"),
        (pl.col("usercmd_mouse_dx").fill_null(0).pow(2) + pl.col("usercmd_mouse_dy").fill_null(0).pow(2)).sqrt().alias("mouse_mag"),
    )
    df = df.with_columns(
        pl.when(pl.col("yaw_diff") > 180).then(360 - pl.col("yaw_diff")).otherwise(pl.col("yaw_diff")).alias("yaw_delta"),
    )
    return df.group_by("steamid").agg(
        pl.col("pitch_delta").mean().alias("aim_pitch_delta_mean"),
        pl.col("pitch_delta").std().alias("aim_pitch_delta_std"),
        pl.col("yaw_delta").mean().alias("aim_yaw_delta_mean"),
        pl.col("yaw_delta").std().alias("aim_yaw_delta_std"),
        pl.col("mouse_mag").mean().alias("aim_mouse_mag_mean"),
        pl.col("mouse_mag").std().alias("aim_mouse_mag_std"),
        pl.col("fov").n_unique().alias("aim_fov_changes"),
        pl.col("is_scoped").mean().alias("aim_scope_time_ratio"),
    )


def compute_combat_features(df: pl.DataFrame) -> pl.DataFrame:
    agg = df.group_by("steamid").agg(
        pl.col("kills_total").max().alias("combat_kills_total"),
        pl.col("deaths_total").max().alias("combat_deaths_total"),
        pl.col("headshot_kills_total").max().alias("combat_hs_total"),
        pl.col("damage_total").max().alias("combat_damage_total"),
        pl.col("total_rounds_played").max().alias("combat_rounds"),
        pl.col("ace_rounds_total").max().alias("combat_ace_rounds"),
        pl.col("4k_rounds_total").max().alias("combat_4k_rounds"),
        pl.col("3k_rounds_total").max().alias("combat_3k_rounds"),
        pl.col("shots_fired").max().alias("combat_shots_fired"),
    )
    return agg.select([
        "steamid",
        (pl.col("combat_kills_total") / pl.when(pl.col("combat_deaths_total") == 0).then(1).otherwise(pl.col("combat_deaths_total"))).alias("combat_kdr"),
        (pl.col("combat_hs_total") / pl.when(pl.col("combat_kills_total") == 0).then(1).otherwise(pl.col("combat_kills_total"))).alias("combat_headshot_ratio"),
        (pl.col("combat_damage_total") / pl.when(pl.col("combat_rounds") == 0).then(1).otherwise(pl.col("combat_rounds"))).alias("combat_damage_per_round"),
        (pl.col("combat_kills_total") / pl.when(pl.col("combat_rounds") == 0).then(1).otherwise(pl.col("combat_rounds"))).alias("combat_kills_per_round"),
        "combat_ace_rounds",
        "combat_4k_rounds",
        "combat_3k_rounds",
        "combat_shots_fired",
    ])


def compute_movement_features(df: pl.DataFrame) -> pl.DataFrame:
    return df.group_by("steamid").agg(
        pl.col("velocity").mean().alias("move_vel_mean"),
        pl.col("velocity").std().alias("move_vel_std"),
        pl.col("velocity").max().alias("move_vel_max"),
        pl.col("is_airborne").mean().alias("move_airborne_ratio"),
        pl.col("duck_amount").mean().alias("move_duck_mean"),
        pl.col("is_walking").mean().alias("move_walk_ratio"),
        pl.col("fall_velo").max().alias("move_fall_vel_max"),
    )


def compute_button_features(df: pl.DataFrame) -> pl.DataFrame:
    return df.group_by("steamid").agg(
        pl.col("FIRE").mean().alias("btn_fire_rate"),
        pl.col("RELOAD").mean().alias("btn_reload_rate"),
        pl.col("ZOOM").mean().alias("btn_zoom_rate"),
    )


def extract_json_features(events: dict) -> pl.DataFrame:
    features = {}

    def _safe_steamid(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, float):
            import math
            if math.isnan(val):
                return None
            return str(int(val))
        if isinstance(val, str):
            return val if val.startswith("Player_") else str(val)
        return str(int(val))

    deaths = events.get("player_death", [])
    for d in deaths:
        attacker = _safe_steamid(d.get("attacker_steamid"))
        if attacker:
            features.setdefault(attacker, {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0})
            features[attacker]["json_kills"] += 1
            if d.get("headshot", False):
                features[attacker]["json_headshots"] += 1

    bullets = events.get("bullet_damage", [])
    for b in bullets:
        attacker = _safe_steamid(b.get("attacker_steamid"))
        if attacker:
            features.setdefault(attacker, {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0})
            if b.get("num_penetrations", 0) > 0:
                features[attacker]["json_wallbangs"] += 1

    if not features:
        return pl.DataFrame(schema={
            "steamid": pl.String, "json_kills": pl.Int64,
            "json_headshots": pl.Int64, "json_wallbangs": pl.Int64, "json_headshot_ratio": pl.Float64,
        })

    rows = [{"steamid": sid, **vals} for sid, vals in features.items()]
    return pl.DataFrame(rows).with_columns(
        (pl.col("json_headshots") / pl.when(pl.col("json_kills") == 0).then(1).otherwise(pl.col("json_kills"))).alias("json_headshot_ratio"),
    )


def build_features(tick_df: pl.DataFrame, events: dict, match_folder: str) -> pl.DataFrame:
    cheaters = get_cheater_set(events)
    tick_df = label_players(tick_df, cheaters, match_folder)

    aim = compute_aim_features(tick_df)
    combat = compute_combat_features(tick_df)
    movement = compute_movement_features(tick_df)
    buttons = compute_button_features(tick_df)
    json_feats = extract_json_features(events)

    df = aim.join(combat, on="steamid", how="left")
    df = df.join(movement, on="steamid", how="left")
    df = df.join(buttons, on="steamid", how="left")
    df = df.join(json_feats, on="steamid", how="left")

    df = df.fill_null(0)

    labels = tick_df.group_by("steamid").agg(
        pl.col("is_cheater").first(),
        pl.col("label_confidence").first(),
    )
    df = df.join(labels, on="steamid", how="left")

    return df


def build_dataset(base_path: Path, max_files: int | None = None) -> pl.DataFrame:
    all_dfs = []
    for folder, label in [("no_cheater_present", 0), ("with_cheater_present", 1)]:
        folder_path = base_path / folder
        files = sorted(folder_path.glob("*.parquet"))
        if max_files:
            files = files[:max_files]
        print(f"Processing {folder}: {len(files)} files...")
        for i, f in enumerate(files):
            idx = int(f.stem)
            try:
                tick_df, events = load_match(folder_path, idx)
                feats = build_features(tick_df, events, folder)
                feats = feats.with_columns(
                    pl.lit(f"{folder}_{idx}").alias("match_id"),
                    pl.lit(label).alias("match_label"),
                )
                all_dfs.append(feats)
            except Exception as e:
                print(f"  Error on {f.name}: {e}")
                continue
            if (i + 1) % 50 == 0:
                print(f"  ...{i + 1}/{len(files)}")
    return pl.concat(all_dfs)
