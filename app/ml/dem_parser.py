"""
Demo file parser (.dem) → tick DataFrame + events dict.
Converts CS2 demo files into the same format as the CS2CD dataset (.parquet + .json),
so the existing feature pipeline can process them identically.

Uses demoparser2 (Rust-based) for fast parsing.
Returns polars DataFrames for downstream memory efficiency.
"""
import numpy as np
import pandas as pd
import polars as pl
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
    "CCSPlayerPawn.m_angEyeAngles",
    "CCSPlayerPawn.CCSPlayer_CameraServices.m_iFOV",
    "CCSPlayerPawn.m_bIsScoped",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iKills",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDeaths",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iHeadShotKills",
    "CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDamage",
    "CCSPlayerPawn.m_iShotsFired",
    "CCSPlayerPawn.m_vecBaseVelocity",
    "CCSPlayerPawn.CCSPlayer_MovementServices.m_flFallVelocity",
    "CCSPlayerPawn.CCSPlayer_MovementServices.m_flDuckAmount",
    "CCSPlayerPawn.m_bIsWalking",
    "CCSPlayerPawn.m_fFlags",
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX",
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY",
    "CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ",
    _bitmask_field(),
    "CCSPlayerPawn.m_iHealth",
    "CCSPlayerPawn.m_ArmorValue",
    "CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount",
    "CCSPlayerController.m_iScore",
    "CCSPlayerController.m_iMVPs",
    "CCSPlayerController.m_iPing",
]


def _is_bit_set(mask: float, bit: int) -> bool:
    if pd.isna(mask):
        return False
    return bool(int(mask) & bit)


def _parse_eye_angles(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    pitch = series.apply(lambda v: float(v[0]) if isinstance(v, (list, np.ndarray)) else 0.0)
    yaw = series.apply(lambda v: float(v[1]) if isinstance(v, (list, np.ndarray)) else 0.0)
    return pitch, yaw


def _parse_velocity(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    vx = series.apply(lambda v: float(v[0]) if isinstance(v, (list, np.ndarray)) else 0.0)
    vy = series.apply(lambda v: float(v[1]) if isinstance(v, (list, np.ndarray)) else 0.0)
    vz = series.apply(lambda v: float(v[2]) if isinstance(v, (list, np.ndarray)) else 0.0)
    return vx, vy, vz


def _downcast_pl(df: pl.DataFrame) -> pl.DataFrame:
    """Downcast numeric columns to float32 / int32 for memory efficiency."""
    schema = {}
    for name, dtype in df.schema.items():
        if dtype in (pl.Float64,):
            schema[name] = pl.Float32
        elif dtype in (pl.Int64, pl.UInt64):
            schema[name] = pl.Int32
        elif dtype in (pl.UInt32,):
            schema[name] = pl.Int32
    if schema:
        df = df.cast(schema, strict=False)
    return df


def parse_dem(filepath: str | Path) -> Tuple[pl.DataFrame, dict]:
    """
    Parse a CS2 .dem file into tick polars DataFrame and events dict.
    """
    from demoparser2 import DemoParser

    filepath = Path(filepath)
    dp = DemoParser(str(filepath))

    pdf = dp.parse_ticks(TICK_PROPS)
    if pdf.empty:
        return pl.DataFrame(), {"player_death": [], "round_freeze_end": []}

    pdf["steamid"] = pdf["steamid"].astype(str)

    pitch, yaw = _parse_eye_angles(pdf["CCSPlayerPawn.m_angEyeAngles"])
    pdf["pitch"] = pitch
    pdf["yaw"] = yaw
    pdf["fov"] = pdf["CCSPlayerPawn.CCSPlayer_CameraServices.m_iFOV"].fillna(0).astype(float)
    pdf["is_scoped"] = pdf["CCSPlayerPawn.m_bIsScoped"].fillna(False).astype(bool)

    pdf["kills_total"] = pdf["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iKills"].fillna(0).astype(int)
    pdf["deaths_total"] = pdf["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDeaths"].fillna(0).astype(int)
    pdf["headshot_kills_total"] = pdf["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iHeadShotKills"].fillna(0).astype(int)
    pdf["damage_total"] = pdf["CCSPlayerController.CCSPlayerController_ActionTrackingServices.m_iDamage"].fillna(0).astype(float)
    pdf["shots_fired"] = pdf["CCSPlayerPawn.m_iShotsFired"].fillna(0).astype(int)

    vx, vy, vz = _parse_velocity(pdf["CCSPlayerPawn.m_vecBaseVelocity"])
    pdf["velocity_X"] = vx
    pdf["velocity_Y"] = vy
    pdf["velocity_Z"] = vz
    pdf["fall_velo"] = pdf["CCSPlayerPawn.CCSPlayer_MovementServices.m_flFallVelocity"].fillna(0).astype(float)
    pdf["duck_amount"] = pdf["CCSPlayerPawn.CCSPlayer_MovementServices.m_flDuckAmount"].fillna(0).astype(float)
    pdf["is_walking"] = pdf["CCSPlayerPawn.m_bIsWalking"].fillna(False).astype(bool)
    pdf["is_airborne"] = ~(pdf["CCSPlayerPawn.m_fFlags"].fillna(0).astype(int) & FL_ONGROUND).astype(bool)

    pdf["X"] = pdf["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecX"].fillna(0).astype(float)
    pdf["Y"] = pdf["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecY"].fillna(0).astype(float)
    pdf["Z"] = pdf["CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vecZ"].fillna(0).astype(float)

    mask_col = _bitmask_field()
    pdf["FIRE"] = pdf[mask_col].apply(lambda v: _is_bit_set(v, IN_ATTACK))
    pdf["RELOAD"] = pdf[mask_col].apply(lambda v: _is_bit_set(v, IN_RELOAD))
    pdf["ZOOM"] = pdf[mask_col].apply(lambda v: _is_bit_set(v, IN_ZOOM))

    pdf["health"] = pdf["CCSPlayerPawn.m_iHealth"].fillna(0).astype(int)
    pdf["armor_value"] = pdf["CCSPlayerPawn.m_ArmorValue"].fillna(0).astype(int)
    pdf["balance"] = pdf["CCSPlayerController.CCSPlayerController_InGameMoneyServices.m_iAccount"].fillna(0).astype(int)
    pdf["score"] = pdf["CCSPlayerController.m_iScore"].fillna(0).astype(int)
    pdf["mvps"] = pdf["CCSPlayerController.m_iMVPs"].fillna(0).astype(int)
    pdf["ping"] = pdf["CCSPlayerController.m_iPing"].fillna(0).astype(int)

    raw = [c for c in TICK_PROPS if c in pdf.columns]
    pdf.drop(columns=raw, inplace=True, errors="ignore")

    # Convert to polars for memory-efficient sort + delta computation
    df = pl.from_pandas(pdf)
    del pdf

    df = _downcast_pl(df)
    df = df.sort(["steamid", "tick"])

    _MOUSE_SCALE = 20.0
    df = df.with_columns(
        (pl.col("yaw").diff().over("steamid").fill_null(0) * _MOUSE_SCALE).alias("usercmd_mouse_dx"),
        (pl.col("pitch").diff().over("steamid").fill_null(0) * _MOUSE_SCALE).alias("usercmd_mouse_dy"),
    )

    df = df.with_columns(
        pl.sqrt(pl.col("velocity_X").pow(2) + pl.col("velocity_Y").pow(2) + pl.col("velocity_Z").pow(2)).alias("velocity"),
    )

    df = df.with_columns(
        pl.lit(0.0).alias("accuracy_penalty"),
        pl.lit(0).alias("ace_rounds_total"),
        pl.lit(0).alias("4k_rounds_total"),
        pl.lit(0).alias("3k_rounds_total"),
    )

    header = dp.parse_header()
    df = df.with_columns(
        pl.lit(header.get("map_name", "Unknown")).alias("map_name"),
    )

    round_starts = dp.parse_event("round_freeze_end")
    num_rounds = len(round_starts)
    df = df.with_columns(pl.lit(num_rounds).alias("total_rounds_played"))

    if num_rounds > 0 and "tick" in round_starts.columns:
        round_thresholds = sorted(round_starts["tick"].dropna().unique().tolist())
        def _assign_round(tick_val: int) -> int:
            for r, t in enumerate(round_thresholds, start=1):
                if tick_val < t:
                    return r - 1
            return len(round_thresholds)
        df = df.with_columns(
            pl.col("tick").map_elements(_assign_round, return_dtype=pl.Int32).alias("round"),
        )
    else:
        df = df.with_columns(pl.lit(0).alias("round"))

    deaths = dp.parse_event("player_death")
    events = {
        "player_death": deaths.to_dict(orient="records") if not deaths.empty else [],
        "round_freeze_end": round_starts.to_dict(orient="records") if not round_starts.empty else [],
        "cheaters": [],
    }

    keep_cols = [
        "steamid", "name", "tick", "pitch", "yaw", "usercmd_mouse_dx", "usercmd_mouse_dy",
        "fov", "is_scoped", "kills_total", "deaths_total", "headshot_kills_total",
        "damage_total", "shots_fired", "accuracy_penalty", "ace_rounds_total",
        "4k_rounds_total", "3k_rounds_total", "velocity", "velocity_X", "velocity_Y",
        "velocity_Z", "is_airborne", "fall_velo", "duck_amount", "is_walking",
        "X", "Y", "Z", "FIRE", "RELOAD", "ZOOM", "total_rounds_played",
        "health", "armor_value", "balance", "score", "mvps", "ping", "map_name", "round",
    ]
    for col in keep_cols:
        if col not in df.columns:
            df = df.with_columns(pl.lit(0).alias(col))

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
        pq_path = cache_dir / f"{stem}.parquet"
        json_path = cache_dir / f"{stem}.json"
        shutil.copy2(shared_pq, pq_path)
        shutil.copy2(shared_json, json_path)
        return str(pq_path), str(json_path)

    tick_df, events = parse_dem(filepath)

    _tmp_pq = shared / f"{stem}.tmp.parquet"
    _tmp_json = shared / f"{stem}.tmp.json"
    tick_df.write_parquet(_tmp_pq)
    import json as _json
    with open(_tmp_json, "w", encoding="utf-8") as f:
        _json.dump(events, f, ensure_ascii=False, default=str)
    _tmp_pq.rename(shared_pq)
    _tmp_json.rename(shared_json)

    pq_path = cache_dir / f"{stem}.parquet"
    json_path = cache_dir / f"{stem}.json"
    shutil.copy2(shared_pq, pq_path)
    shutil.copy2(shared_json, json_path)

    del tick_df, events
    gc.collect()
    return str(pq_path), str(json_path)
