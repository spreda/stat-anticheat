"""
Feature engineering for CS2 anti-cheat.
Transforms per-tick per-player data into player-match feature vectors.
Vectorized for speed.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json

# Feature explanations for UI display
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

# Core numeric columns for anti-cheat
AIM_COLS = ["pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy", "fov", "is_scoped"]
COMBAT_COLS = [
    "kills_total", "deaths_total", "headshot_kills_total", "damage_total",
    "shots_fired", "accuracy_penalty", "ace_rounds_total", "4k_rounds_total", "3k_rounds_total",
]
MOVEMENT_COLS = ["velocity", "velocity_X", "velocity_Y", "velocity_Z", "is_airborne", "fall_velo", "duck_amount", "is_walking"]
POSITION_COLS = ["X", "Y", "Z"]
BUTTON_COLS = ["FIRE", "RELOAD", "ZOOM"]
GAME_COLS = ["total_rounds_played", "health", "armor_value", "balance", "score", "mvps", "ping"]

FEATURE_COLS = AIM_COLS + COMBAT_COLS + MOVEMENT_COLS + POSITION_COLS + BUTTON_COLS + GAME_COLS


def load_match(folder: Path, idx: int) -> tuple[pd.DataFrame, dict]:
    """Load parquet tick data and JSON events for a match."""
    tick_df = pd.read_parquet(folder / f"{idx}.parquet")
    with open(folder / f"{idx}.json", "r") as f:
        events = json.load(f)
    return tick_df, events


def get_cheater_set(events: dict) -> set:
    """Extract cheater steamids from JSON events."""
    cheaters = events.get("cheaters", [])
    return {c["steamid"] for c in cheaters}


def label_players(df: pd.DataFrame, cheater_set: set, match_folder: str) -> pd.DataFrame:
    """Add per-player cheater label with confidence.

    NOTE: "no_cheater_present" matches are NOT manually verified.
    The dataset docs state ~2.8% of players in these matches may
    exhibit cheater-like behaviour. Labels here are noisy.
    Verified cheaters (from JSON) get confidence=1.0.
    Players in clean matches get confidence=0.8 (noisy negatives).
    """
    df = df.copy()
    df["is_cheater"] = df["steamid"].isin(cheater_set).astype(int)
    if match_folder == "no_cheater_present":
        df["label_confidence"] = 0.8
    else:
        df["label_confidence"] = np.where(df["is_cheater"] == 1, 1.0, 0.9)
    return df


def compute_aim_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized aim features per player."""
    # Sort by steamid + tick for proper diff
    df = df.sort_values(["steamid", "tick"])

    # Pitch delta
    df["pitch_delta"] = df.groupby("steamid")["pitch"].diff().abs()

    # Yaw delta with wraparound
    yaw_diff = df.groupby("steamid")["yaw"].diff().abs()
    df["yaw_delta"] = np.where(yaw_diff > 180, 360 - yaw_diff, yaw_diff)

    # Mouse magnitude
    df["mouse_mag"] = np.sqrt(df["usercmd_mouse_dx"].fillna(0) ** 2 + df["usercmd_mouse_dy"].fillna(0) ** 2)

    agg = df.groupby("steamid").agg(
        aim_pitch_delta_mean=("pitch_delta", "mean"),
        aim_pitch_delta_std=("pitch_delta", "std"),
        aim_yaw_delta_mean=("yaw_delta", "mean"),
        aim_yaw_delta_std=("yaw_delta", "std"),
        aim_mouse_mag_mean=("mouse_mag", "mean"),
        aim_mouse_mag_std=("mouse_mag", "std"),
        aim_fov_changes=("fov", "nunique"),
        aim_scope_time_ratio=("is_scoped", "mean"),
    ).reset_index()

    return agg


def compute_combat_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized combat features per player."""
    agg = df.groupby("steamid").agg(
        combat_kills_total=("kills_total", "max"),
        combat_deaths_total=("deaths_total", "max"),
        combat_hs_total=("headshot_kills_total", "max"),
        combat_damage_total=("damage_total", "max"),
        combat_rounds=("total_rounds_played", "max"),
        combat_ace_rounds=("ace_rounds_total", "max"),
        combat_4k_rounds=("4k_rounds_total", "max"),
        combat_3k_rounds=("3k_rounds_total", "max"),
        combat_shots_fired=("shots_fired", "max"),
    ).reset_index()

    agg["combat_kdr"] = agg["combat_kills_total"] / agg["combat_deaths_total"].replace(0, 1)
    agg["combat_headshot_ratio"] = agg["combat_hs_total"] / agg["combat_kills_total"].replace(0, 1)
    agg["combat_damage_per_round"] = agg["combat_damage_total"] / agg["combat_rounds"].replace(0, 1)
    agg["combat_kills_per_round"] = agg["combat_kills_total"] / agg["combat_rounds"].replace(0, 1)

    return agg.drop(columns=["combat_kills_total", "combat_deaths_total", "combat_hs_total", "combat_damage_total", "combat_rounds"])


def compute_movement_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized movement features per player."""
    agg = df.groupby("steamid").agg(
        move_vel_mean=("velocity", "mean"),
        move_vel_std=("velocity", "std"),
        move_vel_max=("velocity", "max"),
        move_airborne_ratio=("is_airborne", "mean"),
        move_duck_mean=("duck_amount", "mean"),
        move_walk_ratio=("is_walking", "mean"),
        move_fall_vel_max=("fall_velo", "max"),
    ).reset_index()
    return agg


def compute_button_features(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized button features per player."""
    agg = df.groupby("steamid").agg(
        btn_fire_rate=("FIRE", "mean"),
        btn_reload_rate=("RELOAD", "mean"),
        btn_zoom_rate=("ZOOM", "mean"),
    ).reset_index()
    return agg


def aggregate_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate numeric columns with mean/std/max per player."""
    cols = [c for c in FEATURE_COLS if c in df.columns]
    numeric = df[cols].select_dtypes(include=[np.number]).columns.tolist()

    agg = {}
    for col in numeric:
        agg[col] = ["mean", "std", "max"]

    grouped = df.groupby("steamid").agg(agg)
    grouped.columns = ["_".join(col).strip() for col in grouped.columns.values]
    return grouped.reset_index()


def extract_json_features(events: dict) -> pd.DataFrame:
    """Extract features from JSON event data per player."""
    features = {}

    def _safe_steamid(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, float):
            # NaN check (NaN is float)
            import math
            if math.isnan(val):
                return None
            return str(int(val))
        if isinstance(val, str):
            return val if val.startswith("Player_") else str(val)
        # numeric (int, numpy int)
        return str(int(val))

    deaths = events.get("player_death", [])
    for d in deaths:
        attacker = _safe_steamid(d.get("attacker_steamid"))
        if attacker:
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            features[attacker]["json_kills"] += 1
            if d.get("headshot", False):
                features[attacker]["json_headshots"] += 1

    bullets = events.get("bullet_damage", [])
    for b in bullets:
        attacker = _safe_steamid(b.get("attacker_steamid"))
        if attacker:
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            if b.get("num_penetrations", 0) > 0:
                features[attacker]["json_wallbangs"] += 1

    if not features:
        return pd.DataFrame(columns=["steamid", "json_kills", "json_headshots", "json_wallbangs", "json_headshot_ratio"])

    df = pd.DataFrame.from_dict(features, orient="index").reset_index().rename(columns={"index": "steamid"})
    df["json_headshot_ratio"] = df["json_headshots"] / df["json_kills"].replace(0, 1)
    return df


def build_features(tick_df: pd.DataFrame, events: dict, match_folder: str) -> pd.DataFrame:
    """Build complete feature vector for a single match."""
    cheaters = get_cheater_set(events)
    tick_df = label_players(tick_df, cheaters, match_folder)

    # Engineered features only (fast, interpretable)
    aim = compute_aim_features(tick_df)
    combat = compute_combat_features(tick_df)
    movement = compute_movement_features(tick_df)
    buttons = compute_button_features(tick_df)
    json_feats = extract_json_features(events)

    # Merge all
    df = aim.merge(combat, on="steamid", how="left")
    df = df.merge(movement, on="steamid", how="left")
    df = df.merge(buttons, on="steamid", how="left")
    df = df.merge(json_feats, on="steamid", how="left")

    # Fill NaN
    df = df.fillna(0)

    # Add label and confidence
    labels = tick_df.groupby("steamid")[["is_cheater", "label_confidence"]].first().reset_index()
    df = df.merge(labels, on="steamid", how="left")

    return df


def build_dataset(base_path: Path, max_files: int | None = None) -> pd.DataFrame:
    """Build full dataset from all matches."""
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
                feats["match_id"] = f"{folder}_{idx}"
                feats["match_label"] = label
                all_dfs.append(feats)
            except Exception as e:
                print(f"  Error on {f.name}: {e}")
                continue
            if (i + 1) % 50 == 0:
                print(f"  ...{i + 1}/{len(files)}")

    return pd.concat(all_dfs, ignore_index=True)
