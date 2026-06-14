"""
Demo file parser (.dem) → tick DataFrame + events dict.
Converts CS2 demo files into the same format as the CS2CD dataset (.parquet + .json),
so the existing feature pipeline can process them identically.

Uses demoparser2 (Rust-based) for fast parsing.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple

# ── Button bitmask constants ──────────────────────────────────────────
IN_ATTACK = 1 << 0       # 1
IN_JUMP = 1 << 1         # 2
IN_DUCK = 1 << 2         # 4
IN_FORWARD = 1 << 3      # 8
IN_BACK = 1 << 4         # 16
IN_USE = 1 << 5          # 32
IN_LEFT = 1 << 9         # 512
IN_RIGHT = 1 << 10       # 1024
IN_ZOOM = 1 << 12        # 4096
IN_RELOAD = 1 << 17      # 131072

# ── Flag constants ────────────────────────────────────────────────────
FL_ONGROUND = 1 << 0     # 1


def _bitmask_field() -> str:
    """Return the demoparser2 field name for button down mask."""
    return "CCSPlayerPawn.CCSPlayer_MovementServices.m_nButtonDownMaskPrev"


# ── Field lists for demoparser2 ───────────────────────────────────────

TICK_PROPS = [
    # Aim / view angles
    "CCSPlayerPawn.m_angEyeAngles",               # -> pitch, yaw
    "CCSPlayerPawn.CCSPlayer_CameraServices.m_iFOV",  # -> fov
    "CCSPlayerPawn.m_bIsScoped",                  # -> is_scoped

    # Combat
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iKills",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDeaths",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iHeadShotKills",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDamage",
    "CCSPlayerPawn.m_iShotsFired",

    # Movement
    "CCSPlayerPawn.m_vecBaseVelocity",            # -> velocity_X/Y/Z
    "CCSPlayerPawn.CCSPlayer_MovementServices.m_flFallVelocity",  # -> fall_velo
    "CCSPlayerPawn.CCSPlayer_MovementServices.m_flDuckAmount",    # -> duck_amount
    "CCSPlayerPawn.m_bIsWalking",                 # -> is_walking
    "CCSPlayerPawn.m_fFlags",                     # -> is_airborne

    # Position (from CBodyComponent)
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX",
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY",
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ",

    # Buttons
    _bitmask_field(),

    # Player state
    "CCSPlayerPawn.m_iHealth",
    "CCSPlayerPawn.m_ArmorValue",
    "CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount",
    "CCSPlayerController.m_iScore",
    "CCSPlayerController.m_iMVPs",
    "CCSPlayerController.m_iPing",
]


def _is_bit_set(mask: float, bit: int) -> bool:
    """Check if a specific bit is set in a button mask."""
    if pd.isna(mask):
        return False
    return bool(int(mask) & bit)


def _parse_eye_angles(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Split m_angEyeAngles vector column into pitch and yaw series."""
    # The column contains lists/arrays of [pitch, yaw, roll]
    pitch = series.apply(lambda v: float(v[0]) if isinstance(v, (list, np.ndarray)) else 0.0)
    yaw = series.apply(lambda v: float(v[1]) if isinstance(v, (list, np.ndarray)) else 0.0)
    return pitch, yaw


def _parse_velocity(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Split m_vecBaseVelocity vector column into X, Y, Z series."""
    vx = series.apply(lambda v: float(v[0]) if isinstance(v, (list, np.ndarray)) else 0.0)
    vy = series.apply(lambda v: float(v[1]) if isinstance(v, (list, np.ndarray)) else 0.0)
    vz = series.apply(lambda v: float(v[2]) if isinstance(v, (list, np.ndarray)) else 0.0)
    return vx, vy, vz


def parse_dem(filepath: str | Path) -> Tuple[pd.DataFrame, dict]:
    """
    Parse a CS2 .dem file into tick DataFrame and events dict.

    Returns
    -------
    tick_df : pd.DataFrame
        Per-tick per-player data with column names matching the parquet dataset.
    events : dict
        Dict with 'player_death' and 'round_freeze_end' lists (compatible with
        the existing extract_match_events and feature pipeline).
    """
    from demoparser2 import DemoParser

    filepath = Path(filepath)
    dp = DemoParser(str(filepath))

    # ── Parse ticks ───────────────────────────────────────────────
    raw = dp.parse_ticks(TICK_PROPS)
    if raw.empty:
        return pd.DataFrame(), {"player_death": [], "round_freeze_end": []}

    df = raw.copy()

    # Ensure steamid is string for consistent merging
    df["steamid"] = df["steamid"].astype(str)

    # ── Map columns ───────────────────────────────────────────────
    # Aim
    pitch, yaw = _parse_eye_angles(df["CCSPlayerPawn.m_angEyeAngles"])
    df["pitch"] = pitch
    df["yaw"] = yaw
    df["fov"] = df["CCSPlayerPawn.CCSPlayer_CameraServices.m_iFOV"].fillna(0).astype(float)
    df["is_scoped"] = df["CCSPlayerPawn.m_bIsScoped"].fillna(False).astype(bool)

    # Approximate usercmd_mouse_dx/dy from angular changes between ticks.
    # usercmd_mouse_dx ~ yaw_delta, usercmd_mouse_dy ~ pitch_delta.
    # Scale factor 20 puts mean mouse_mag in ~3-14 range (matching real CS2 data).
    _MOUSE_SCALE = 20.0
    df = df.sort_values(["steamid", "tick"])
    _yaw_delta = df.groupby("steamid")["yaw"].diff().fillna(0)
    _yaw_delta = np.where(_yaw_delta > 180, 360 - _yaw_delta, _yaw_delta)  # wraparound
    _yaw_delta = np.where(_yaw_delta < -180, _yaw_delta + 360, _yaw_delta)
    _pitch_delta = df.groupby("steamid")["pitch"].diff().fillna(0)
    df["usercmd_mouse_dx"] = _yaw_delta * _MOUSE_SCALE
    df["usercmd_mouse_dy"] = _pitch_delta * _MOUSE_SCALE

    # Combat
    df["kills_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iKills"].fillna(0).astype(int)
    df["deaths_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDeaths"].fillna(0).astype(int)
    df["headshot_kills_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iHeadShotKills"].fillna(0).astype(int)
    df["damage_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDamage"].fillna(0).astype(float)
    df["shots_fired"] = df["CCSPlayerPawn.m_iShotsFired"].fillna(0).astype(int)
    df["accuracy_penalty"] = 0.0   # not available per-player
    df["ace_rounds_total"] = 0     # not available in .dem
    df["4k_rounds_total"] = 0      # not available in .dem
    df["3k_rounds_total"] = 0      # not available in .dem

    # Movement
    vx, vy, vz = _parse_velocity(df["CCSPlayerPawn.m_vecBaseVelocity"])
    df["velocity_X"] = vx
    df["velocity_Y"] = vy
    df["velocity_Z"] = vz
    df["velocity"] = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
    df["fall_velo"] = df["CCSPlayerPawn.CCSPlayer_MovementServices.m_flFallVelocity"].fillna(0).astype(float)
    df["duck_amount"] = df["CCSPlayerPawn.CCSPlayer_MovementServices.m_flDuckAmount"].fillna(0).astype(float)
    df["is_walking"] = df["CCSPlayerPawn.m_bIsWalking"].fillna(False).astype(bool)
    # Airborne: NOT on ground (FL_ONGROUND flag is bit 0 in m_fFlags)
    df["is_airborne"] = ~(df["CCSPlayerPawn.m_fFlags"].fillna(0).astype(int) & FL_ONGROUND).astype(bool)

    # Position
    df["X"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX"].fillna(0).astype(float)
    df["Y"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY"].fillna(0).astype(float)
    df["Z"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ"].fillna(0).astype(float)

    # Buttons (from bitmask)
    mask_col = _bitmask_field()
    df["FIRE"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_ATTACK))
    df["RELOAD"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_RELOAD))
    df["ZOOM"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_ZOOM))

    # Player state
    df["health"] = df["CCSPlayerPawn.m_iHealth"].fillna(0).astype(int)
    df["armor_value"] = df["CCSPlayerPawn.m_ArmorValue"].fillna(0).astype(int)
    df["balance"] = df["CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount"].fillna(0).astype(int)
    df["score"] = df["CCSPlayerController.m_iScore"].fillna(0).astype(int)
    df["mvps"] = df["CCSPlayerController.m_iMVPs"].fillna(0).astype(int)
    df["ping"] = df["CCSPlayerController.m_iPing"].fillna(0).astype(int)

    # Map name (from header)
    header = dp.parse_header()
    df["map_name"] = header.get("map_name", "Unknown")

    # ── Parse round info ──────────────────────────────────────────
    round_starts = dp.parse_event("round_freeze_end")
    num_rounds = len(round_starts)
    df["total_rounds_played"] = num_rounds

    # Assign round number based on tick thresholds
    if num_rounds > 0 and "tick" in round_starts.columns:
        round_thresholds = sorted(round_starts["tick"].dropna().unique().tolist())
        def _assign_round(tick: int) -> int:
            for r, t in enumerate(round_thresholds, start=1):
                if tick < t:
                    return r - 1
            return len(round_thresholds)
        df["round"] = df["tick"].apply(_assign_round)
    else:
        df["round"] = 0

    # ── Parse events ──────────────────────────────────────────────
    deaths = dp.parse_event("player_death")
    events = {
        "player_death": deaths.to_dict(orient="records") if not deaths.empty else [],
        "round_freeze_end": round_starts.to_dict(orient="records") if not round_starts.empty else [],
        "cheaters": [],  # .dem files don't have cheater labels
    }

    # ── Drop raw demoparser columns ───────────────────────────────
    keep_cols = {
        "steamid", "name", "tick", "pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy",
        "fov", "is_scoped", "kills_total", "deaths_total", "headshot_kills_total",
        "damage_total", "shots_fired", "accuracy_penalty", "ace_rounds_total",
        "4k_rounds_total", "3k_rounds_total", "velocity", "velocity_X", "velocity_Y",
        "velocity_Z", "is_airborne", "fall_velo", "duck_amount", "is_walking",
        "X", "Y", "Z", "FIRE", "RELOAD", "ZOOM", "total_rounds_played",
        "health", "armor_value", "balance", "score", "mvps", "ping", "map_name", "round",
    }
    existing_keep = [c for c in keep_cols if c in df.columns]
    df = df[existing_keep].copy()

    # Ensure all expected columns exist (fill missing with 0)
    for col in keep_cols:
        if col not in df.columns:
            df[col] = 0

    return df, events


def parse_dem_to_cache(filepath: str | Path, cache_dir: str | Path) -> Tuple[str, str]:
    """
    Parse .dem file and save as parquet + json in a cache directory.

    Returns
    -------
    parquet_path : str
    json_path : str
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(filepath).stem
    tick_df, events = parse_dem(filepath)

    pq_path = cache_dir / f"{stem}.parquet"
    json_path = cache_dir / f"{stem}.json"

    tick_df.to_parquet(pq_path, index=False)
    import json
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, default=str)

    return str(pq_path), str(json_path)
