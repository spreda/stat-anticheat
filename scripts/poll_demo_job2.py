import requests, time, sys

job_id = sys.argv[1] if len(sys.argv) > 1 else '3f71d187-c361-422d-9f05-a7e04e63983c'
url = f'http://127.0.0.1:8000/job/{job_id}'

for i in range(60):
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        status = data.get('status', 'unknown')
        print(f'Poll {i}: status={status}')
        if data.get('result'):
            r2 = data['result']
            print(f'  Result keys: {list(r2.keys())}')
            if r2.get('players'):
                p = r2['players'][0]
                feats = p.get('features', {})
                print(f'  First player mouse: {feats.get("mouse_mag_mean")}')
                print(f'  First player yaw_std: {feats.get("aim_yaw_std")}')
                print(f'  match_info: {r2.get("match_info", {}).get("map")}')
            if r2.get('summary'):
                print(f'  Summary: {r2["summary"]}')
        if status in ('done', 'error'):
            break
    except Exception as e:
        print(f'Poll {i}: error={e}')
    time.sleep(2)