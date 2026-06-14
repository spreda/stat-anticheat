"""Download a CS2 .dem file from various public sources."""
import os, json, sys
import urllib.request

def try_download(url, dest_name):
    """Try to download a file, return True if successful .dem"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        resp = urllib.request.urlopen(req, timeout=60)
        data = resp.read()
        print(f"  OK: {len(data)} bytes")
        if len(data) < 50000:
            print(f"  Too small, skipping")
            return False
        # Check demo header
        if data[:4] in (b"HL2\x01", b"PBUF"):
            print(f"  -> VALID .DEM FILE!")
            fname = f"downloads/{dest_name}"
            os.makedirs("downloads", exist_ok=True)
            with open(fname, "wb") as f:
                f.write(data)
            print(f"  -> Saved to {fname}")
            return True
        else:
            print(f"  Not a .dem file (header: {data[:8]})")
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

# Source 1: HF dataset API to find CS2CD files
print("=== 1. CS2CD HuggingFace dataset ===")
try:
    url = "https://huggingface.co/api/datasets/Skytnt/CS2CD"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    found = 0
    for sib in data.get("siblings", []):
        name = sib.get("rfilename", "")
        if name.endswith(".dem"):
            print(f"Found .dem: {name}")
            found += 1
    if found == 0:
        print("No .dem files in HF dataset (likely parquet/csv only)")
        for sib in data.get("siblings", [])[:20]:
            print(f"  {sib.get('rfilename', '?')}")
except Exception as e:
    print(f"HF API: {e}")

# Source 2: Try csstats.gg API
print("\n=== 2. Google search for free .dem files ===")
try:
    # Use a simple search via a known dump
    # The CSGO/CSCZ official demo downloads
    pass
except Exception as e:
    print(f"Error: {e}")

# Source 3: Try known CS2 demo archives 
print("\n=== 3. Known demo archives ===")
demos_to_try = [
    # Various known public CS2 demos
    ("https://raw.githubusercontent.com/SatGoby/cs2-demo-test/main/test.dem", "test_goby.dem"),
]

for url, name in demos_to_try:
    print(f"Trying {url}...")
    try_download(url, name)

# Source 4: Check if we can use cs2 demo from ESL/ESEA web
print("\n=== 4. Checking available dataset files ===")
# The CS2CD was created from csstats.gg. They parsed .dem -> csv.gz + json.
# Original .dem files are NOT in the dataset (only processed data)
# But we already have 2 .dem files locally.

local_dems = []
import glob
for f in glob.glob("datasets/**/*.dem", recursive=True):
    size = os.path.getsize(f)
    local_dems.append((f, size))
    print(f"  {f} ({size/1024/1024:.1f} MB)")

if not local_dems:
    print("No local .dem files found.")

print("\nDone.")