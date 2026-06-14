"""Try to find/download CS2 demo files for testing."""
import requests, sys, os

urls = [
    "https://github.com/LaihoE/demoparser-wasm-demo/raw/main/test.dem",
    "https://raw.githubusercontent.com/LaihoE/demoparser-wasm-demo/main/test.dem",
]

headers = {"User-Agent": "Mozilla/5.0"}
found = False
for url in urls:
    try:
        r = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
        cl = r.headers.get("Content-Length", "0")
        print(f"{url[:60]:60s} -> {r.status_code} ({cl} bytes)")
        if r.status_code == 200 and int(cl or "0") > 100000:
            print(f"  DOWNLOADING...")
            r2 = requests.get(url, timeout=120, stream=True, headers=headers)
            dest = "datasets/matches/test_cheater.dem"
            with open(dest, "wb") as f:
                for chunk in r2.iter_content(8192):
                    f.write(chunk)
            print(f"  Saved to {dest} ({os.path.getsize(dest)} bytes)")
            found = True
            break
    except Exception as e:
        print(f"{url[:60]:60s} -> ERROR: {e}")

if not found:
    print("No accessible demo found.")
    print()
    print("Suggestions for manually downloading cheater demos:")
    print("  1. https://csgostats.gg/ - find matches with VAC banned players")
    print("  2. https://www.hltv.org/demos - pro match demos")
    print("  3. Any Faceit/ESEA match with known cheater bans")
    print()
    print("Already have 317 cheater matches in datasets/cs2cd_dataset/with_cheater_present/")
    print("Use those .parquet files to test the model on known cheaters.")