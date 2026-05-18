import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\app")))
from ml.features import build_dataset

BASE = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset")
df = build_dataset(BASE, max_files=20)
print(f"Built: {len(df)} records, {df['is_cheater'].sum()} cheaters")
print("Columns:", list(df.columns)[:20])
print("Label confidence distribution:", df["label_confidence"].value_counts().to_dict())
