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


def _downcast(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast numeric columns to reduce memory (float64→float32, int64→int32)."""
    for col in df.columns:
        col_type = df[col].dtype
        if col_type == "float64":
            df[col] = pd.to_numeric(df[col], downcast="float")
        elif col_type == "int64":
            df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def _raw_cols() -> list:
    """Return raw demoparser2 column names that have been derived into new columns."""
    return list(TICK_PROPS)


def parse_dem(filepath: str | Path) -> Tuple[pd.DataFrame, dict]:
    """
    Parse a CS2 .dem file into tick DataFrame and events dict.
    Memory-optimised: drops raw columns and downcasts before expensive operations.
    """
    from demoparser2 import DemoParser

    filepath = Path(filepath)
    dp = DemoParser(str(filepath))

    df = dp.parse_ticks(TICK_PROPS)
    if df.empty:
        return pd.DataFrame(), {"player_death": [], "round_freeze_end": []}

    df["steamid"] = df["steamid"].astype(str)

    # ── Derive columns from raw parser columns ────────────────────
    pitch, yaw = _parse_eye_angles(df["CCSPlayerPawn.m_angEyeAngles"])
    df["pitch"] = pitch
    df["yaw"] = yaw
    df["fov"] = df["CCSPlayerPawn.CCSPlayer_CameraServices.m_iFOV"].fillna(0).astype(float)
    df["is_scoped"] = df["CCSPlayerPawn.m_bIsScoped"].fillna(False).astype(bool)

    df["kills_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iKills"].fillna(0).astype(int)
    df["deaths_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDeaths"].fillna(0).astype(int)
    df["headshot_kills_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iHeadShotKills"].fillna(0).astype(int)
    df["damage_total"] = df["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDamage"].fillna(0).astype(float)
    df["shots_fired"] = df["CCSPlayerPawn.m_iShotsFired"].fillna(0).astype(int)

    vx, vy, vz = _parse_velocity(df["CCSPlayerPawn.m_vecBaseVelocity"])
    df["velocity_X"] = vx
    df["velocity_Y"] = vy
    df["velocity_Z"] = vz
    df["fall_velo"] = df["CCSPlayerPawn.CCSPlayer_MovementServices.m_flFallVelocity"].fillna(0).astype(float)
    df["duck_amount"] = df["CCSPlayerPawn.CCSPlayer_MovementServices.m_flDuckAmount"].fillna(0).astype(float)
    df["is_walking"] = df["CCSPlayerPawn.m_bIsWalking"].fillna(False).astype(bool)
    df["is_airborne"] = ~(df["CCSPlayerPawn.m_fFlags"].fillna(0).astype(int) & FL_ONGROUND).astype(bool)

    df["X"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX"].fillna(0).astype(float)
    df["Y"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY"].fillna(0).astype(float)
    df["Z"] = df["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ"].fillna(0).astype(float)

    mask_col = _bitmask_field()
    df["FIRE"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_ATTACK))
    df["RELOAD"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_RELOAD))
    df["ZOOM"] = df[mask_col].apply(lambda v: _is_bit_set(v, IN_ZOOM))

    df["health"] = df["CCSPlayerPawn.m_iHealth"].fillna(0).astype(int)
    df["armor_value"] = df["CCSPlayerPawn.m_ArmorValue"].fillna(0).astype(int)
    df["balance"] = df["CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount"].fillna(0).astype(int)
    df["score"] = df["CCSPlayerController.m_iScore"].fillna(0).astype(int)
    df["mvps"] = df["CCSPlayerController.m_iMVPs"].fillna(0).astype(int)
    df["ping"] = df["CCSPlayerController.m_iPing"].fillna(0).astype(int)

    # Drop all raw demoparser columns (free memory before expensive ops)
    df.drop(columns=[c for c in _raw_cols() if c in df.columns], inplace=True, errors="ignore")

    # ── Downcast BEFORE sort (smaller data = less swap) ───────────
    df = _downcast(df)

    # ── Sort for delta computation ────────────────────────────────
    df.sort_values(["steamid", "tick"], inplace=True)

    # Mouse deltas (on downcasted, sorted data)
    _MOUSE_SCALE = 20.0
    _yaw_delta = df.groupby("steamid")["yaw"].diff().fillna(0)
    _yaw_delta = np.where(_yaw_delta > 180, 360 - _yaw_delta, _yaw_delta)
    _yaw_delta = np.where(_yaw_delta < -180, _yaw_delta + 360, _yaw_delta)
    _pitch_delta = df.groupby("steamid")["pitch"].diff().fillna(0)
    df["usercmd_mouse_dx"] = _yaw_delta * _MOUSE_SCALE
    df["usercmd_mouse_dy"] = _pitch_delta * _MOUSE_SCALE

    df["velocity"] = np.sqrt(df["velocity_X"] ** 2 + df["velocity_Y"] ** 2 + df["velocity_Z"] ** 2)

    # Static columns (no per-player info available in .dem)
    df["accuracy_penalty"] = 0.0
    df["ace_rounds_total"] = 0
    df["4k_rounds_total"] = 0
    df["3k_rounds_total"] = 0

    # Map name
    header = dp.parse_header()
    df["map_name"] = header.get("map_name", "Unknown")

    # ── Round info ────────────────────────────────────────────────
    round_starts = dp.parse_event("round_freeze_end")
    num_rounds = len(round_starts)
    df["total_rounds_played"] = num_rounds

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

    # ── Events ────────────────────────────────────────────────────
    deaths = dp.parse_event("player_death")
    events = {
        "player_death": deaths.to_dict(orient="records") if not deaths.empty else [],
        "round_freeze_end": round_starts.to_dict(orient="records") if not round_starts.empty else [],
        "cheaters": [],
    }

    # ── Ensure expected columns exist ─────────────────────────────
    keep_cols = {
        "steamid", "name", "tick", "pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy",
        "fov", "is_scoped", "kills_total", "deaths_total", "headshot_kills_total",
        "damage_total", "shots_fired", "accuracy_penalty", "ace_rounds_total",
        "4k_rounds_total", "3k_rounds_total", "velocity", "velocity_X", "velocity_Y",
        "velocity_Z", "is_airborne", "fall_velo", "duck_amount", "is_walking",
        "X", "Y", "Z", "FIRE", "RELOAD", "ZOOM", "total_rounds_played",
        "health", "armor_value", "balance", "score", "mvps", "ping", "map_name", "round",
    }
    for col in keep_cols:
        if col not in df.columns:
            df[col] = 0

    return df, events


# Shared cache for parsed .dem files (reused across job runs).
# Files are .dem → .parquet + .json once, then re-linked for each job.
_DEM_CACHE_DIR = None


def _get_dem_cache() -> Path:
    global _DEM_CACHE_DIR
    if _DEM_CACHE_DIR is None:
        _DEM_CACHE_DIR = Path(__file__).parent.parent.parent / "uploads" / ".dem_cache"
        _DEM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Clean stale .tmp files from interrupted writes
        for f in _DEM_CACHE_DIR.glob("*.tmp.*"):
            f.unlink(missing_ok=True)
    return _DEM_CACHE_DIR


def parse_dem_to_cache(filepath: str | Path, cache_dir: str | Path) -> Tuple[str, str]:
    """
    Parse .dem file and save as parquet + json in a cache directory.
    Uses a shared cache so the same .dem is only parsed once.

    Returns
    -------
    parquet_path : str
    json_path : str
    """
    import shutil
    import gc
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(filepath).stem
    shared = _get_dem_cache()
    shared_pq = shared / f"{stem}.parquet"
    shared_json = shared / f"{stem}.json"

    if shared_pq.exists() and shared_json.exists():
        # Copy cached files into job dir (fast file copy, not re-parse)
        pq_path = cache_dir / f"{stem}.parquet"
        json_path = cache_dir / f"{stem}.json"
        shutil.copy2(shared_pq, pq_path)
        shutil.copy2(shared_json, json_path)
        return str(pq_path), str(json_path)

    tick_df, events = parse_dem(filepath)

    # Atomically write to shared cache (temp file + rename to avoid partial writes)
    _tmp_pq = shared / f"{stem}.tmp.parquet"
    _tmp_json = shared / f"{stem}.tmp.json"
    tick_df.to_parquet(_tmp_pq, index=False)
    import json as _json
    with open(_tmp_json, "w", encoding="utf-8") as f:
        _json.dump(events, f, ensure_ascii=False, default=str)
    _tmp_pq.rename(shared_pq)
    _tmp_json.rename(shared_json)

    # Also save to job dir
    pq_path = cache_dir / f"{stem}.parquet"
    json_path = cache_dir / f"{stem}.json"
    shutil.copy2(shared_pq, pq_path)
    shutil.copy2(shared_json, json_path)

    del tick_df, events
    gc.collect()
    return str(pq_path), str(json_path)
