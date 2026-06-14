"""Check player names from demo files."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from app.ml.dem_parser import parse_dem

df, events = parse_dem("datasets/matches/b8-vs-fut-m2-overpass.dem")
names = df[["steamid","name"]].drop_duplicates(subset="steamid")
print("=== Player names from overpass.dem ===")
print(names.to_string())

# Check a NEW analysis (with name fix)
r = requests.get("http://127.0.0.1:8000/job/b5118e02-bbe8-4b5a-91c3-3aed727ffd1a", timeout=10)
d = r.json()
players = d.get("result", {}).get("players", [])
print("\n=== Report players ===")
for p in players:
    print(f'  name={p.get("name","?")} steamid={p["steamid"][:20]}')