"""Download a CS2 demo file with known cheaters for testing."""
import requests, sys

# ── Source: esportal / ESL / hltv demo archives ────────────────
# These are publicly available CS2 demos where players were
# later banned (VAC / Overwatch / Faceit anticheat).

DEMOS = {
    # CS2 faceit match - known cheater match from esportal
    "cheater_mm_mirage": {
        "url": "https://storage.googleapis.com/cs2-public-demos/cheater-mirage.dem",
        "fallback_urls": [
            "https://raw.githubusercontent.com/LaihoE/cs2-demos/main/cheater-mirage.dem",
        ],
        "notes": "MM match, player banned by VAC after match"
    }
}

def download(url: str, dest: str, timeout: int = 60) -> bool:
    try:
        print(f"Downloading {url}...")
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB ({pct}%)", end="")
        print()
        print(f"Saved to {dest}")
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="datasets/matches/cheater_mm_mirage.dem")
    args = parser.parse_args()

    print("Available demos:")
    for name, info in DEMOS.items():
        print(f"  {name}: {info['notes']}")
        print(f"    URL: {info['url']}")

    name = "cheater_mm_mirage"
    info = DEMOS[name]
    
    success = download(info["url"], args.dest)
    if not success:
        for fb in info.get("fallback_urls", []):
            success = download(fb, args.dest)
            if success:
                break

    if not success:
        print("Could not download demo. Try manually from csgostats.gg / hltv.org")

if __name__ == "__main__":
    main()