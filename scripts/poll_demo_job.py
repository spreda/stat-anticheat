import requests, time, sys

job_id = sys.argv[1] if len(sys.argv) > 1 else '9ebf51ed-02a2-4eb3-9576-923344331196'
url = f'http://127.0.0.1:8000/job/{job_id}'

for i in range(60):
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        status = data.get('status', 'unknown')
        print(f'Poll {i}: status={status}')
        if data.get('result'):
            print(f'  Result keys: {list(data["result"].keys())}')
            if data['result'].get('players'):
                print(f'  Players: {len(data["result"]["players"])}')
        if status in ('done', 'error'):
            break
    except Exception as e:
        print(f'Poll {i}: error={e}')
    time.sleep(2)
