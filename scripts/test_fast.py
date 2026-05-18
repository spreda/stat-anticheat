import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\app")))
from ml.features import build_dataset

BASE = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset")
t0 = time.time()
df = build_dataset(BASE, max_files=10)
t1 = time.time()
print(f"Done: {len(df)} records, {df['is_cheater'].sum()} cheaters, {len(df.columns)} cols, {t1-t0:.1f}s")
print("Columns:", list(df.columns))
