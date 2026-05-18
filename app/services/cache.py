
"""
Cache service for dataset match analysis results.
"""
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent.parent / "uploads" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cache_key(folder: str, idx: int) -> str:
    return f"{folder}_{idx}.json"


def load_cached(folder: str, idx: int) -> dict | None:
    path = CACHE_DIR / get_cache_key(folder, idx)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cached(folder: str, idx: int, result: dict) -> None:
    path = CACHE_DIR / get_cache_key(folder, idx)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def clear_cache() -> int:
    removed = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            removed += 1
        except Exception:
            pass
    return removed
