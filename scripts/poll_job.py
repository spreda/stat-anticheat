import requests, time

job_id = 'ea0b3311-a4ba-4863-af69-180660b8985a'
url = f'http://127.0.0.1:8000/job/{job_id}'

for i in range(10):
    res = requests.get(url)
    data = res.json()
    status = data['status']
    print(f'Step {i}: status={status}')
    if status in ('done', 'error'):
        print('Result:', data.get('result'))
        break
    time.sleep(2)
