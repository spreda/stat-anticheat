"""Run fresh analysis for ancient.dem with fixes."""
import requests, time

def main():
    r = requests.get(
        "http://127.0.0.1:8000/analyze-demo/b8-vs-fut-m1-ancient.dem",
        allow_redirects=False, timeout=120
    )
    loc = r.headers.get("Location", "")
    job_id = loc.split("job=")[-1]
    print("Job ID:", job_id)

    for i in range(60):
        r = requests.get(f"http://127.0.0.1:8000/job/{job_id}", timeout=10)
        d = r.json()
        s = d.get("status")
        print(f"Poll {i}: {s}")
        if s == "done" and d.get("result"):
            r2 = d["result"]
            mi = r2.get("match_info", {})
            print(f"  map={mi.get('map')} rounds={mi.get('rounds')} duration={mi.get('duration')}")
            for p in r2.get("players", []):
                f = p.get("features", {})
                print(f"  {p['steamid'][:12]} risk={p['risk_score']} mouse={f.get('mouse_mag_mean')} yaw={f.get('aim_yaw_std')} kdr={f.get('kdr')}")
            break
        if s == "error":
            print(f"  ERROR: {d.get('result', {}).get('message')}")
            break
        time.sleep(2)

if __name__ == "__main__":
    main()