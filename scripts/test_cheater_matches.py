"""Test model on known cheater matches from the dataset."""
import sys, os, json, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from app.services.analyzer import analyze_match, load_model
from app.db import init_db, create_job, get_job

init_db()

for match_id in [0, 1, 5, 10, 50]:
    folder = "with_cheater_present"
    pq_path = f"datasets/cs2cd_dataset/{folder}/{match_id}.parquet"
    json_path = f"datasets/cs2cd_dataset/{folder}/{match_id}.json"
    if not os.path.exists(pq_path):
        continue

    print(f"\n=== Match #{match_id} ({folder}) ===")
    tick_df = pd.read_parquet(pq_path)
    with open(json_path) as f:
        events = json.load(f)

    cheaters = events.get("cheaters", [])
    cheat_steamids = set()
    for c in cheaters:
        if isinstance(c, dict):
            cheat_steamids.add(c.get("steamid"))
        else:
            cheat_steamids.add(str(c))
    print(f"Known cheaters: {len(cheat_steamids)}")

    job_id = str(uuid.uuid4())
    create_job(job_id, pq_path, f"{folder}/{match_id}")
    analyze_match(job_id, pq_path, events=events)

    job = get_job(job_id)
    if job and job.get("result"):
        result = json.loads(job["result"])
        if result.get("players"):
            for p in result["players"]:
                sid = p["steamid"]
                is_cheat = sid in cheat_steamids
                flag = "CHEATER" if is_cheat else "clean"
                print(f"  risk={p['risk_score']:3d} flagged={p['flagged']} {flag:8s} mouse={p['features']['mouse_mag_mean']}")
        print(f"  Summary: {result.get('summary')}")