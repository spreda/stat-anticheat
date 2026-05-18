import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\app")))
from ml.features import load_match, build_features

folder = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset\with_cheater_present")
t0 = time.time()
tick_df, events = load_match(folder, 0)
t1 = time.time()
print(f"Load: {t1-t0:.1f}s, shape={tick_df.shape}")

t0 = time.time()
feats = build_features(tick_df, events, "with_cheater_present")
t1 = time.time()
print(f"Features: {t1-t0:.1f}s, shape={feats.shape}")
print(f"Cols: {len(feats.columns)}")
print(f"Cheaters: {feats['is_cheater'].sum()}")
print("Columns:", list(feats.columns))
print(feats.head())
