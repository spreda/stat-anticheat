# CS2 Anti-Cheat Analyzer

Offline analysis system for Counter-Strike 2 match recordings. Upload a `.parquet` match file and receive per-player risk scores with explainable feature breakdowns.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Train model (demo on 20 files, or full dataset)
python scripts/train_demo.py      # quick demo (~2 min)
python scripts/train_subset.py    # 100 files for better accuracy

# 3. Start server
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 4. Open browser
# http://127.0.0.1:8000
```

## Project Structure

```
anticheat/
├── app/
│   ├── main.py              # FastAPI server
│   ├── db.py                # SQLite job tracking
│   ├── services/
│   │   └── analyzer.py      # feature extraction + model scoring
│   ├── ml/
│   │   └── features.py      # vectorized feature engineering (33 feats)
│   ├── templates/
│   │   ├── upload.html      # drag-and-drop upload
│   │   ├── report.html      # risk score table
│   │   └── error.html       # error page
│   └── static/css/
│       └── style.css        # dark theme
├── scripts/
│   ├── eda.py               # dataset inspection
│   ├── train_demo.py        # quick 20-file training
│   ├── train_subset.py      # 100-file subset training
│   └── test_one.py          # single-file profiling
├── models/
│   └── model_v1.joblib      # trained XGBoost model
├── datasets/
│   └── cs2cd_dataset/       # 795 matches (parquet + JSON)
├── uploads/                 # uploaded files + jobs.db
├── requirements.txt
├── PLAN_MVP.md
└── PLAN_FULL.md
```

## How It Works

1. **Upload** — analyst uploads a `.parquet` match file via web UI
2. **Feature Engineering** — system extracts 33 anti-cheat features per player:
   - **Aim**: pitch/yaw delta std, mouse magnitude, scope time
   - **Combat**: KDR, headshot ratio, damage per round, ace/4k/3k rounds
   - **Movement**: velocity stats, airborne/duck/walk ratios
   - **Actions**: fire/reload/zoom button rates
   - **JSON Events**: kills, headshots, wallbangs from event data
3. **ML Scoring** — XGBoost classifier outputs probability → risk score 0-100
4. **Report** — players sorted by risk, flagged if above threshold

## Dataset

- **Source**: CS2CD (Counter-Strike 2 Cheat Detection Dataset)
- **Size**: 795 matches — 478 clean, 317 with cheaters
- **Format**: `.parquet` (tick-level per-player) + `.json` (events & labels)
- **Label Quality**: Only "with cheater" matches verified via VAC bans. Clean matches unverified — ~2.8% may contain undetected cheaters.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Upload page |
| `/upload` | POST | Upload parquet file, returns job_id |
| `/job/{job_id}` | GET | Job status and results (JSON) |
| `/report/{job_id}` | GET | HTML report page |
| `/docs` | GET | Auto-generated API docs |

## Model Performance (Demo)

Trained on 20 files (200 player-records):
- **AUC**: 0.999
- **F1**: 0.975
- **Top Features**: `json_headshots`, `move_vel_mean`, `move_walk_ratio`, `combat_kdr`

## Tech Stack

- **Backend**: Python 3.14, FastAPI, SQLite
- **ML**: pandas, pyarrow, scikit-learn, XGBoost, joblib
- **Frontend**: Jinja2 + vanilla JS, dark theme CSS

## Next Steps (Full Project)

See `PLAN_FULL.md` for complete roadmap including:
- Full dataset training with cross-validation
- Temporal features (reaction time, pre-fire, wallbang rate)
- Admin dashboard and job list
- Batch upload and export
- pytest test suite
- Docker deployment

## License

Diploma project. Dataset from CS2CD — cite appropriately.
