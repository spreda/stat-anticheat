"""Test script: analyze a .dem and verify results."""
import requests, time, sys

def main():
    if len(sys.argv) > 1:
        job_id = sys.argv[1]
    else:
        # Start analysis
        resp = requests.get(
            "http://127.0.0.1:8000/analyze-demo/b8-vs-fut-m2-overpass.dem",
            allow_redirects=False, timeout=120
        )
        loc = resp.headers.get("Location", "")
        job_id = loc.split("job=")[-1]
        print("Job ID:", job_id)

    # Poll
    for i in range(60):
        r = requests.get(f"http://127.0.0.1:8000/job/{job_id}", timeout=10)
        data = r.json()
        s = data.get("status")
        print(f"Poll {i}: status={s}")
        if s == "done" and data.get("result"):
            r2 = data["result"]
            # Check match_info
            mi = r2.get("match_info", {})
            print(f"  map: {mi.get('map')}")
            print(f"  rounds: {mi.get('rounds')}")
            print(f"  duration: {mi.get('duration')}")
            # Check player features
            players = r2.get("players", [])
            print(f"  players: {len(players)}")
            for p in players:
                feats = p.get("features", {})
                mouse = feats.get("mouse_mag_mean", 0)
                yaw = feats.get("aim_yaw_std", 0)
                print(f"  {p['steamid'][:8]}... risk={p['risk_score']} mouse={mouse} yaw={yaw}")
            break
        if s == "error":
            print(f"  ERROR: {data.get('result', {}).get('message')}")
            break
        time.sleep(2)

if __name__ == "__main__":
    main()