"""
Optimized feature engineering for CS2 anti-cheat (v2 — sequential + streaming).
Key optimizations:
  1. Single combined groupby per match (instead of 4 separate ones)
  2. Explicit del + gc.collect() after each file to minimize memory peaks
  3. Streaming concat: accumulates small DFs, periodically merges to cut peak RAM
  4. sys.stdout.flush() for real-time progress in PowerShell
"""
import sys
import gc
import json
from pathlib import Path

import pandas as pd
import numpy as np


def _extract_json_features(events: dict) -> dict[str, dict[str, float]]:
    """Extract JSON event features per player. Returns dict of steamid -> features."""
    features: dict[str, dict[str, float]] = {}

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

    for d in events.get("player_death", []):
        attacker = _safe_steamid(d.get("attacker_steamid"))
        if attacker:
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            features[attacker]["json_kills"] += 1
            if d.get("headshot", False):
                features[attacker]["json_headshots"] += 1

    for b in events.get("bullet_damage", []):
        attacker = _safe_steamid(b.get("attacker_steamid"))
        if attacker:
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            if b.get("num_penetrations", 0) > 0:
                features[attacker]["json_wallbangs"] += 1

    # Compute ratio
    for v in features.values():
        v["json_headshot_ratio"] = v["json_headshots"] / max(v["json_kills"], 1)

    return features


def _process_one_match(parquet_path: Path, match_folder: str, match_label: int) -> pd.DataFrame | None:
    """Process one match → compact DataFrame (one row per player).
    Single combined groupby + explicit gc to minimize memory.
    """
    json_path = parquet_path.parent / f"{parquet_path.stem}.json"
    match_id = f"{match_folder}_{parquet_path.stem}"

    try:
        tick_df = pd.read_parquet(parquet_path)
        with open(json_path, "r") as f:
            events = json.load(f)
    except Exception as e:
        print(f"  ERROR loading {parquet_path.name}: {e}", flush=True)
        return None

    # --- Labels ---
    cheater_set = {c["steamid"] for c in events.get("cheaters", [])}
    is_cheater = tick_df["steamid"].isin(cheater_set).values
    tick_df["is_cheater"] = is_cheater.astype(np.int8)
    if match_folder == "no_cheater_present":
        tick_df["label_confidence"] = 0.8
    else:
        tick_df["label_confidence"] = np.where(is_cheater, 1.0, 0.9)

    # --- Sort once for diff-based features ---
    tick_df.sort_values(["steamid", "tick"], inplace=True)

    # --- Derived columns BEFORE groupby ---
    pitch_delta = tick_df.groupby("steamid")["pitch"].diff().abs()
    yaw_diff = tick_df.groupby("steamid")["yaw"].diff().abs()
    tick_df["pitch_delta"] = pitch_delta
    tick_df["yaw_delta"] = np.where(yaw_diff > 180, 360 - yaw_diff, yaw_diff)
    tick_df["mouse_mag"] = np.sqrt(
        tick_df["usercmd_mouse_dx"].fillna(0).values ** 2
        + tick_df["usercmd_mouse_dy"].fillna(0).values ** 2
    )

    # --- Single combined groupby ---
    agg_dict = {
        "pitch_delta": ["mean", "std"],
        "yaw_delta": ["mean", "std"],
        "mouse_mag": ["mean", "std"],
        "fov": "nunique",
        "is_scoped": "mean",
        "kills_total": "max",
        "deaths_total": "max",
        "headshot_kills_total": "max",
        "damage_total": "max",
        "total_rounds_played": "max",
        "ace_rounds_total": "max",
        "4k_rounds_total": "max",
        "3k_rounds_total": "max",
        "shots_fired": "max",
        "velocity": ["mean", "std", "max"],
        "is_airborne": "mean",
        "duck_amount": "mean",
        "is_walking": "mean",
        "fall_velo": "max",
        "FIRE": "mean",
        "RELOAD": "mean",
        "ZOOM": "mean",
        "is_cheater": "first",
        "label_confidence": "first",
    }
    available = set(tick_df.columns)
    agg_dict = {k: v for k, v in agg_dict.items() if k in available}
    agg = tick_df.groupby("steamid").agg(agg_dict)

    # Free big tick_df immediately
    del tick_df
    gc.collect()

    # Flatten columns
    agg.columns = ["_".join(c).strip("_") for c in agg.columns]
    agg = agg.reset_index()

    # Rename to canonical names
    rename_map = {
        "pitch_delta_mean": "aim_pitch_delta_mean",
        "pitch_delta_std": "aim_pitch_delta_std",
        "yaw_delta_mean": "aim_yaw_delta_mean",
        "yaw_delta_std": "aim_yaw_delta_std",
        "mouse_mag_mean": "aim_mouse_mag_mean",
        "mouse_mag_std": "aim_mouse_mag_std",
        "fov_nunique": "aim_fov_changes",
        "is_scoped_mean": "aim_scope_time_ratio",
        "kills_total_max": "combat_kills_total",
        "deaths_total_max": "combat_deaths_total",
        "headshot_kills_total_max": "combat_hs_total",
        "damage_total_max": "combat_damage_total",
        "total_rounds_played_max": "combat_rounds",
        "ace_rounds_total_max": "combat_ace_rounds",
        "4k_rounds_total_max": "combat_4k_rounds",
        "3k_rounds_total_max": "combat_3k_rounds",
        "shots_fired_max": "combat_shots_fired",
        "velocity_mean": "move_vel_mean",
        "velocity_std": "move_vel_std",
        "velocity_max": "move_vel_max",
        "is_airborne_mean": "move_airborne_ratio",
        "duck_amount_mean": "move_duck_mean",
        "is_walking_mean": "move_walk_ratio",
        "fall_velo_max": "move_fall_vel_max",
        "FIRE_mean": "btn_fire_rate",
        "RELOAD_mean": "btn_reload_rate",
        "ZOOM_mean": "btn_zoom_rate",
        "is_cheater_first": "is_cheater",
        "label_confidence_first": "label_confidence",
    }
    agg.rename(columns={k: v for k, v in rename_map.items() if k in agg.columns}, inplace=True)

    # Derived combat features
    if "combat_kills_total" in agg.columns and "combat_deaths_total" in agg.columns:
        agg["combat_kdr"] = agg["combat_kills_total"] / agg["combat_deaths_total"].replace(0, 1)
    if "combat_hs_total" in agg.columns and "combat_kills_total" in agg.columns:
        agg["combat_headshot_ratio"] = agg["combat_hs_total"] / agg["combat_kills_total"].replace(0, 1)
    if "combat_damage_total" in agg.columns and "combat_rounds" in agg.columns:
        agg["combat_damage_per_round"] = agg["combat_damage_total"] / agg["combat_rounds"].replace(0, 1)
    if "combat_kills_total" in agg.columns and "combat_rounds" in agg.columns:
        agg["combat_kills_per_round"] = agg["combat_kills_total"] / agg["combat_rounds"].replace(0, 1)

    agg.drop(columns=[c for c in [
        "combat_kills_total", "combat_deaths_total", "combat_hs_total",
        "combat_damage_total", "combat_rounds",
    ] if c in agg.columns], inplace=True)

    # JSON features
    jf = _extract_json_features(events)
    if jf:
        jdf = pd.DataFrame.from_dict(jf, orient="index").reset_index()
        jdf.rename(columns={"index": "steamid"}, inplace=True)
        agg = agg.merge(jdf, on="steamid", how="left")
    else:
        for col in ["json_kills", "json_headshots", "json_wallbangs", "json_headshot_ratio"]:
            agg[col] = 0

    agg.fillna(0, inplace=True)
    agg["match_id"] = match_id
    agg["match_label"] = match_label
    return agg


def build_dataset_fast(
    base_path: Path,
    max_files: int | None = None,
    chunk_size: int = 50,
) -> pd.DataFrame:
    """Build dataset sequentially with streaming concat to cut peak RAM.

    Processes files one by one. Every chunk_size files, concatenates accumulated
    small DataFrames into one and frees the small ones — keeps only 1 large DF
    in memory instead of 795 small ones.
    """
    all_chunks: list[pd.DataFrame] = []
    total_players = 0
    errors = 0
    done = 0

    for folder, label in [("no_cheater_present", 0), ("with_cheater_present", 1)]:
        folder_path = base_path / folder
        parquet_files = sorted(folder_path.glob("*.parquet"))
        if max_files:
            parquet_files = parquet_files[:max_files]
        total = len(parquet_files)
        print(f"Processing {folder}: {total} files...", flush=True)

        for i, f in enumerate(parquet_files):
            result = _process_one_match(f, folder, label)
            done += 1
            if result is not None:
                total_players += len(result)
                all_chunks.append(result)
            else:
                errors += 1

            # Periodically merge chunks to cut peak RAM
            if len(all_chunks) >= chunk_size:
                batch = pd.concat(all_chunks, ignore_index=True)
                all_chunks = [batch]
                gc.collect()

            if done % 50 == 0:
                print(f"  ...{done}/795 ({errors} errors, {total_players} players)", flush=True)

    if all_chunks:
        df = pd.concat(all_chunks, ignore_index=True)
    else:
        df = pd.DataFrame()

    print(f"Done: {len(df)} player-records, {errors} errors", flush=True)
    return df


# Legacy alias for train_model_fast.py compatibility
build_dataset_parallel = build_dataset_fast
