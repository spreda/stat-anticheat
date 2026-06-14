"""
FastAPI backend for CS2 Anti-Cheat Analyzer.
"""
from fastapi import FastAPI, Request, UploadFile, File, Form, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import shutil
import uuid
import json
from datetime import datetime

from app.services.analyzer import analyze_match, extract_match_info, load_model
from app.services.dataset_browser import list_all_matches, get_match_info, list_demo_matches
from app.services.cache import load_cached, save_cached
from app.db import init_db, get_job, create_job, update_job, get_job_stats
from app.ml.dem_parser import parse_dem_to_cache

BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

DATASET_DIR = BASE_DIR.parent / "datasets" / "cs2cd_dataset"

app = FastAPI(title="CS2 Anti-Cheat Analyzer", version="1.0")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return a user-friendly error page."""
    logging.getLogger(__name__).exception("Unhandled error on %s %s", request.method, request.url.path)
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            render_template("error.html", {
                "request": request,
                "message": f"Внутренняя ошибка сервера: {exc}",
            }),
            status_code=500,
        )
    return JSONResponse({"error": f"Внутренняя ошибка сервера: {exc}"}, status_code=500)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Manual Jinja2 rendering to avoid Python 3.14 cache bug
from jinja2 import Environment, FileSystemLoader
_jinja_env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")))

def render_template(name: str, context: dict) -> str:
    template = _jinja_env.get_template(name)
    return template.render(**context)


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse(render_template("upload.html", {"request": request, "active_page": "upload"}))


@app.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
):
    """Upload a match file for analysis."""
    # Validate
    if not (file.filename.endswith(".parquet") or file.filename.endswith(".dem")):
        return JSONResponse({"error": "Only .parquet or .dem files accepted"}, status_code=400)

    job_id = str(uuid.uuid4())
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    # Save uploaded file
    uploaded_path = job_dir / file.filename
    with open(uploaded_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Convert .dem → .parquet + .json if needed
    if file.filename.endswith(".dem"):
        try:
            pq_path, json_path = parse_dem_to_cache(uploaded_path, job_dir)
        except Exception as e:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
            return JSONResponse({"error": f"Не удалось распарсить .dem файл: {e}"}, status_code=422)
        match_file_path = pq_path
    else:
        match_file_path = str(job_dir / "match.parquet")
        import os
        os.rename(uploaded_path, match_file_path)

    # Save metadata
    meta_path = job_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump({"original_name": file.filename, "uploaded_at": datetime.utcnow().isoformat(), "user_metadata": json.loads(metadata)}, f)

    # Create job record
    create_job(job_id, str(match_file_path), file.filename)

    # Queue analysis — pass events if .dem was converted
    def _run_analysis():
        import traceback
        try:
            _pq_dir = Path(match_file_path).parent
            _json_candidates = list(_pq_dir.glob("*.json"))
            _evts = None
            if _json_candidates:
                try:
                    with open(_json_candidates[0], "r", encoding="utf-8") as _f:
                        _evts = json.load(_f)
                except Exception:
                    pass
            analyze_match(job_id, str(match_file_path), events=_evts)
        except Exception:
            err_msg = traceback.format_exc()
            update_job(job_id, "error", json.dumps({"status": "error", "message": f"Ошибка анализа: {err_msg}"}))

    background_tasks.add_task(_run_analysis)

    return {"job_id": job_id, "status": "pending"}


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status and results."""
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return {
        "job_id": job["id"],
        "status": job["status"],
        "filename": job["filename"],
        "created_at": job["created_at"],
        "result": json.loads(job["result"]) if job["result"] else None,
    }


@app.get("/report/{job_id}", response_class=HTMLResponse)
async def report_page(request: Request, job_id: str):
    """Show analysis report page."""
    job = get_job(job_id)
    if not job:
        return HTMLResponse(render_template("error.html", {"request": request, "message": "Job not found"}))

    result = json.loads(job["result"]) if job["result"] else None
    from app.ml.features import FEATURE_EXPLANATIONS
    return HTMLResponse(render_template("report.html", {
        "request": request,
        "job": job,
        "result": result,
        "feature_explanations": FEATURE_EXPLANATIONS,
        "active_page": "upload",
    }))


# ─────────────────────────────────────────
# Dataset routes
# ─────────────────────────────────────────

@app.get("/dataset", response_class=HTMLResponse)
async def dataset_page(
    request: Request,
    filter_type: str = Query("all", alias="type"),
    page: int = Query(1),
):
    """Browse dataset matches."""
    data = list_all_matches(filter_type=filter_type, page=page, per_page=24)

    # Cache check
    for m in data["matches"]:
        m["cached"] = load_cached(m["folder"], m["idx"]) is not None

    return HTMLResponse(render_template("dataset.html", {
        "request": request,
        "matches": data["matches"],
        "filter_type": filter_type,
        "page": data["page"],
        "total_pages": data["total_pages"],
        "total_matches": data["total_matches"],
        "clean_count": data["clean_count"],
        "cheat_count": data["cheat_count"],
        "active_page": "dataset",
    }))


@app.get("/analyze-dataset/{folder}/{idx}")
async def analyze_dataset(
    folder: str,
    idx: int,
    background_tasks: BackgroundTasks,
):
    """Analyze a dataset match — redirect immediately, process in background."""
    if folder not in ("no_cheater_present", "with_cheater_present"):
        return JSONResponse({"error": "Invalid folder"}, status_code=400)

    cached = load_cached(folder, idx)
    if cached:
        return RedirectResponse(url=f"/report-dataset/{folder}/{idx}")

    job_id = str(uuid.uuid4())
    file_path = DATASET_DIR / folder / f"{idx}.parquet"
    if not file_path.exists():
        return JSONResponse({"error": "Match file not found"}, status_code=404)

    create_job(job_id, str(file_path), f"dataset:{folder}/{idx}")

    def _analyze_and_cache():
        import traceback
        try:
            json_path = DATASET_DIR / folder / f"{idx}.json"
            events = {}
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    events = json.load(f)
            except Exception:
                events = {"cheaters": []}

            import pandas as pd
            tick_df = pd.read_parquet(file_path)
            match_info = extract_match_info(tick_df, events, folder, idx)
            analyze_match(job_id, str(file_path), events=events, match_info=match_info, tick_df=tick_df)
            del tick_df

            job = get_job(job_id)
            if job and job.get("result"):
                try:
                    result = json.loads(job["result"])
                    if result.get("status") == "done":
                        save_cached(folder, idx, result)
                except Exception:
                    pass
        except Exception:
            err_msg = traceback.format_exc()
            update_job(job_id, "error", json.dumps({"status": "error", "message": f"Ошибка анализа: {err_msg}"}))

    background_tasks.add_task(_analyze_and_cache)

    return RedirectResponse(url=f"/report-dataset/{folder}/{idx}?job={job_id}")


@app.get("/report-dataset/{folder}/{idx}", response_class=HTMLResponse)
async def report_dataset_page(request: Request, folder: str, idx: int, job: str = Query(None)):
    """Show report for a dataset match — cached or polling."""
    result = load_cached(folder, idx)
    if result:
        from app.ml.features import FEATURE_EXPLANATIONS
        return HTMLResponse(render_template("report.html", {
            "request": request,
            "job": {"filename": f"dataset:{folder}/{idx}", "status": "done", "id": "cached"},
            "result": result,
            "feature_explanations": FEATURE_EXPLANATIONS,
            "active_page": "dataset",
        }))

    # If job provided and not done yet, show polling page
    if job:
        job_row = get_job(job)
        if job_row:
            status = job_row.get("status", "pending")
            result = json.loads(job_row["result"]) if job_row.get("result") else None
            if status == "done" and result:
                # Analysis just finished — reload cached result
                cached = load_cached(folder, idx)
                if cached:
                    from app.ml.features import FEATURE_EXPLANATIONS
                    return HTMLResponse(render_template("report.html", {
                        "request": request,
                        "job": {"filename": f"dataset:{folder}/{idx}", "status": "done", "id": job},
                        "result": cached,
                        "feature_explanations": FEATURE_EXPLANATIONS,
                        "active_page": "dataset",
                    }))
            if status == "error":
                return HTMLResponse(render_template("report.html", {
                    "request": request,
                    "job": {"filename": f"dataset:{folder}/{idx}", "status": "error", "id": job},
                    "result": result or {"message": "Неизвестная ошибка при анализе матча."},
                    "feature_explanations": {},
                    "active_page": "dataset",
                }))
            return HTMLResponse(render_template("polling.html", {
                "request": request,
                "job_id": job,
                "redirect_url": f"/report-dataset/{folder}/{idx}?job={job}",
                "active_page": "dataset",
            }))

    # No job and no cache — redirect to dataset
    return RedirectResponse(url="/dataset")


# ─────────────────────────────────────────
# Demo match routes (datasets/matches/)
# ─────────────────────────────────────────

MATCHES_DIR = BASE_DIR.parent / "datasets" / "matches"


@app.get("/analyze-demo/{filename:path}")
async def analyze_demo(
    filename: str,
    background_tasks: BackgroundTasks,
):
    """Analyze a .dem file from datasets/matches/."""
    demo_path = MATCHES_DIR / filename
    if not demo_path.exists() or not filename.endswith(".dem"):
        return JSONResponse({"error": "Demo file not found"}, status_code=404)

    job_id = str(uuid.uuid4())
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    # Convert .dem → parquet + json
    try:
        pq_path, json_path = parse_dem_to_cache(demo_path, job_dir)
    except Exception as e:
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)
        return JSONResponse({"error": f"Не удалось распарсить .dem файл: {e}"}, status_code=422)
    create_job(job_id, pq_path, f"demo:{filename}")

    def _analyze():
        import traceback
        try:
            events = {}
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    events = json.load(f)
            except Exception:
                events = {"player_death": [], "round_freeze_end": [], "cheaters": []}

            import pandas as pd
            tick_df = pd.read_parquet(pq_path)
            match_info = extract_match_info(tick_df, events, "matches", filename)
            analyze_match(job_id, pq_path, events=events, match_info=match_info, tick_df=tick_df)
            del tick_df
        except Exception:
            err_msg = traceback.format_exc()
            update_job(job_id, "error", json.dumps({"status": "error", "message": f"Ошибка анализа: {err_msg}"}))

    background_tasks.add_task(_analyze)
    return RedirectResponse(url=f"/report-demo/{filename}?job={job_id}")


@app.get("/report-demo/{filename:path}", response_class=HTMLResponse)
async def report_demo_page(request: Request, filename: str, job: str = Query(None)):
    """Show report for a demo match — polling or done."""
    if job:
        job_row = get_job(job)
        if job_row:
            status = job_row.get("status", "pending")
            result = json.loads(job_row["result"]) if job_row.get("result") else None
            if status == "done" and result:
                from app.ml.features import FEATURE_EXPLANATIONS
                return HTMLResponse(render_template("report.html", {
                    "request": request,
                    "job": {"filename": f"demo:{filename}", "status": "done", "id": job},
                    "result": result,
                    "feature_explanations": FEATURE_EXPLANATIONS,
                    "active_page": "dataset",
                }))
            if status == "error":
                return HTMLResponse(render_template("report.html", {
                    "request": request,
                    "job": {"filename": f"demo:{filename}", "status": "error", "id": job},
                    "result": result or {"message": "Неизвестная ошибка при анализе демо-файла."},
                    "feature_explanations": {},
                    "active_page": "dataset",
                }))
            return HTMLResponse(render_template("polling.html", {
                "request": request,
                "job_id": job,
                "redirect_url": f"/report-demo/{filename}?job={job}",
                "active_page": "dataset",
            }))

    # No job — redirect to dataset
    return RedirectResponse(url="/dataset")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """System settings and model info."""
    stats = get_job_stats()
    data = list_all_matches(filter_type="all", page=1, per_page=1)
    stats["total_matches"] = data["clean_count"] + data["cheat_count"]
    stats["clean_matches"] = data["clean_count"]
    stats["cheat_matches"] = data["cheat_count"]

    # Model info
    artifact = load_model()
    model_info = None
    if artifact:
        model_type = artifact.get("type", "single")
        feature_importances = artifact.get("feature_importances", {})
        if model_type == "ensemble":
            try:
                model = artifact.get("model")
                if model and hasattr(model, "feature_importances_"):
                    importances = model.feature_importances_
                    fnames = artifact.get("feature_names", [])
                    feature_importances = dict(zip(fnames, importances.tolist())) if len(fnames) == len(importances) else {}
            except Exception:
                pass
        top_features = []
        if isinstance(feature_importances, dict) and feature_importances:
            max_imp = max(feature_importances.values())
            top_features = sorted(
                [{"name": k, "importance": round(v, 4), "importance_percent": round(v / max_imp * 100, 1)} for k, v in feature_importances.items()],
                key=lambda x: x["importance"],
                reverse=True,
            )[:5]
        model_info = {
            "algorithm": f"{'Ensemble' if model_type == 'ensemble' else 'XGBoost'}",
            "version": artifact.get("version", "v1"),
            "n_features": len(artifact.get("feature_names", [])),
            "threshold": artifact.get("threshold", 0.5),
            "trained_at": artifact.get("trained_at", "?"),
            "top_features": top_features,
        }

    settings = {
        "threshold": 0.5,
        "min_risk_display": 0,
        "cache_enabled": True,
        "locked": True,
    }

    from app.ml.features import FEATURE_EXPLANATIONS

    return HTMLResponse(render_template("settings.html", {
        "request": request,
        "stats": stats,
        "model_info": model_info,
        "settings": settings,
        "feature_explanations": FEATURE_EXPLANATIONS,
        "active_page": "settings",
    }))


@app.get("/api/docs")
async def api_docs():
    """Redirect to auto-generated docs."""
    return {"docs": "/docs"}
