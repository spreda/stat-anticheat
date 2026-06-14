
"""
Dataset browser: scans CS2CD dataset folders and demo files, returns match metadata.
"""
from pathlib import Path
import json

DATASET_DIR = Path(__file__).parent.parent.parent / "datasets" / "cs2cd_dataset"
MATCHES_DIR = Path(__file__).parent.parent.parent / "datasets" / "matches"


def _scan_folder(folder: str) -> list:
    folder_path = DATASET_DIR / folder
    if not folder_path.exists():
        return []
    parquet_files = {f.stem for f in folder_path.glob("*.parquet")}
    json_files = {f.stem for f in folder_path.glob("*.json")}
    paired = sorted(int(s) for s in (parquet_files & json_files) if s.isdigit())
    return paired


def _scan_demo_matches() -> list[dict]:
    """Scan datasets/matches/ for .dem files and return metadata for each."""
    if not MATCHES_DIR.exists():
        return []
    demos = sorted(MATCHES_DIR.glob("*.dem"))
    matches = []
    for i, f in enumerate(demos):
        size_mb = f.stat().st_size / (1024 * 1024)
        matches.append({
            "idx": i + 1,
            "filename": f.name,
            "path": str(f.absolute()),
            "size_mb": round(size_mb, 1),
            "folder": "matches",
            "cached": False,
            "has_cheater": False,
        })
    return matches


def _read_json(folder: str, idx: int) -> dict:
    path = DATASET_DIR / folder / f"{idx}.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def list_matches(folder: str, page: int = 1, per_page: int = 24) -> dict:
    """List matches for a given folder with pagination."""
    ids = _scan_folder(folder)
    total_matches = len(ids)
    total_pages = max(1, (total_matches + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_ids = ids[start:end]

    matches = []
    for idx in page_ids:
        data = _read_json(folder, idx)
        cheaters = data.get("cheaters") or []
        matches.append({
            "id": idx,
            "folder": folder,
            "cheaters": len(cheaters),
            "cached": False,
            "status": "ready",
        })

    return {
        "matches": matches,
        "page": page,
        "total_pages": total_pages,
        "total_matches": total_matches,
    }


def list_demo_matches(page: int = 1, per_page: int = 24) -> dict:
    """List .demo matches with pagination."""
    all_demos = _scan_demo_matches()
    total_matches = len(all_demos)
    total_pages = max(1, (total_matches + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_demos = all_demos[start:end]

    return {
        "matches": page_demos,
        "page": page,
        "total_pages": total_pages,
        "total_matches": total_matches,
    }


def list_all_matches(filter_type: str = "all", page: int = 1, per_page: int = 24) -> dict:
    """List matches across both folders with filtering and pagination. Returns also demo match count."""
    clean_ids = _scan_folder("no_cheater_present")
    cheat_ids = _scan_folder("with_cheater_present")
    demo_matches = _scan_demo_matches()

    clean_count = len(clean_ids)
    cheat_count = len(cheat_ids)
    demo_count = len(demo_matches)

    if filter_type == "clean":
        all_matches = [(i, "no_cheater_present") for i in clean_ids]
    elif filter_type == "cheat":
        all_matches = [(i, "with_cheater_present") for i in cheat_ids]
    elif filter_type == "demos":
        all_matches = [(m["filename"], "matches") for m in demo_matches]
    else:
        all_matches = [(i, "no_cheater_present") for i in clean_ids] + [(i, "with_cheater_present") for i in cheat_ids]
        all_matches.sort(key=lambda x: x[0], reverse=True)

    total_matches = len(all_matches)
    total_pages = max(1, (total_matches + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_matches = all_matches[start:end]

    matches = []
    for idx_or_name, folder in page_matches:
        if folder == "matches":
            # Demo match
            dm = next((m for m in demo_matches if m["filename"] == idx_or_name), None)
            if dm:
                matches.append({
                    "idx": dm["idx"],
                    "folder": "matches",
                    "has_cheater": False,
                    "filename": dm["filename"],
                    "size_mb": dm["size_mb"],
                    "players": "?",
                    "rounds": "?",
                    "rows_formatted": "—",
                    "cached": dm["cached"],
                })
        else:
            # CS2CD dataset match
            idx = int(idx_or_name)
            data = _read_json(folder, idx)
            cheaters = data.get("cheaters") or []
            pq_path = DATASET_DIR / folder / f"{idx}.parquet"
            rows = 0
            try:
                import pyarrow.parquet as pq
                meta = pq.read_metadata(str(pq_path))
                rows = meta.num_rows
            except Exception:
                pass
            matches.append({
                "idx": idx,
                "folder": folder,
                "has_cheater": len(cheaters) > 0,
                "filename": f"{idx}.parquet",
                "players": len(cheaters) if cheaters else "?",
                "rounds": len(data.get("gameRounds", [])),
                "rows_formatted": f"{rows:,}".replace(",", " "),
                "cached": False,
            })

    return {
        "matches": matches,
        "page": page,
        "total_pages": total_pages,
        "total_matches": total_matches,
        "clean_count": clean_count,
        "cheat_count": cheat_count,
        "demo_count": demo_count,
    }


from typing import Optional


def get_match_info(folder: str, idx: int) -> Optional[dict]:
    """Return metadata for a specific match."""
    pq_path = DATASET_DIR / folder / f"{idx}.parquet"
    json_path = DATASET_DIR / folder / f"{idx}.json"
    if not pq_path.exists() and not json_path.exists():
        return None
    data = _read_json(folder, idx)
    cheaters = data.get("cheaters") or []
    return {
        "id": idx,
        "folder": folder,
        "cheaters": cheaters,
        "has_parquet": pq_path.exists(),
        "has_json": json_path.exists(),
        "json_keys": list(data.keys()),
    }
