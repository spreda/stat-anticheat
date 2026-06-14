"""Evaluate with CORRECT per-player labels (not match-level)."""
import warnings
warnings.filterwarnings("ignore")
import sys, os, json, time
import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from ml.features import build_features

MODELS = os.path.join(os.path.dirname(__file__), "..", "models")
ens = joblib.load(os.path.join(MODELS, "ensemble_config_v1.joblib"))
sup_art = joblib.load(os.path.join(MODELS, "supervised_v1.joblib"))
iso_art = joblib.load(os.path.join(MODELS, "isolation_forest_v1.joblib"))
sup = sup_art["model"] if isinstance(sup_art, dict) else sup_art
iso = iso_art["model"] if isinstance(iso_art, dict) else iso_art
fnames = ens["feature_names"]
scaler = ens["scaler"]
ws, wa = float(ens["supervised_weight"]), float(ens["anomaly_weight"])

DS = os.path.join(os.path.dirname(__file__), "..", "datasets", "cs2cd_dataset")
import random; random.seed(42)

# Sample 40 from each class for speed
cheat_files = sorted(os.listdir(os.path.join(DS, "with_cheater_present")))
clean_files = sorted(os.listdir(os.path.join(DS, "no_cheater_present")))
sample_cheat = random.sample(cheat_files, min(40, len(cheat_files)))
sample_clean = random.sample(clean_files, min(40, len(clean_files)))

from ml.features import get_cheater_set

rows_data = []  # list of (features_row, per_player_label)
t0 = time.time()

for subdir, files in [("with_cheater_present", sample_cheat), ("no_cheater_present", sample_clean)]:
    folder = os.path.join(DS, subdir)
    for f in files:
        fp = os.path.join(folder, f)
        try:
            tick = pd.read_parquet(fp)
            jf = fp.replace(".parquet", ".json")
            events = json.load(open(jf)) if os.path.exists(jf) else {}
            feats = build_features(tick, events, subdir)

            # Per-player labeling using cheater steamids from JSON
            cheater_set = get_cheater_set(events)
            for _, row in feats.iterrows():
                player_label = 1 if row["steamid"] in cheater_set else 0
                rows_data.append((row, player_label))
        except:
            pass

elapsed = time.time() - t0
print(f"Done: {len(rows_data)} players from 80 matches in {elapsed:.0f}s")

# Build arrays
X_all = np.array([[float(row.get(f, 0)) for f in fnames] for row, _ in rows_data])
X_all = np.nan_to_num(X_all, nan=0.0, posinf=1e6, neginf=-1e6)
y_all = np.array([label for _, label in rows_data])

n_cheater = (y_all == 1).sum()
n_clean = (y_all == 0).sum()
print(f"  True cheaters: {n_cheater}, Clean/non-cheaters: {n_clean}")

X_sc = scaler.transform(X_all)
sup_p = sup.predict_proba(X_sc)[:, 1]
iso_s = iso.decision_function(X_sc)
iso_r = 1 - (iso_s - iso_s.min()) / (iso_s.max() - iso_s.min() + 1e-8)
proba = ws * sup_p + wa * iso_r

from sklearn.metrics import roc_auc_score
auc = roc_auc_score(y_all, proba)
print(f"\nAUC-ROC: {auc:.4f}")

print(f"\n{'t':>5} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>5} {'FP':>5} {'TN':>5} {'FN':>5} {'Acc':>6}")
print("-" * 58)
best_f1, best_t = 0, 0
for t in np.arange(0.10, 0.90, 0.02):
    pred = (proba >= t).astype(int)
    tp = ((pred == 1) & (y_all == 1)).sum()
    fp = ((pred == 1) & (y_all == 0)).sum()
    tn = ((pred == 0) & (y_all == 0)).sum()
    fn = ((pred == 0) & (y_all == 1)).sum()
    prec = tp / (tp + fp + 1e-8)
    rec = tp / (tp + fn + 1e-8)
    f1 = 2 * prec * rec / (prec + rec + 1e-8)
    acc = (tp + tn) / len(y_all)
    if f1 > best_f1:
        best_f1, best_t = f1, t
    print(f"{t:5.2f} {prec:6.3f} {rec:6.3f} {f1:6.3f} {tp:5d} {fp:5d} {tn:5d} {fn:5d} {acc:6.3f}")
print(f"\nBest F1={best_f1:.3f} at t={best_t:.2f}")

# Score distributions
for name, val in [("Cheater (true)", 1), ("Clean/non-cheater", 0)]:
    s = proba[y_all == val]
    print(f"{name}: n={len(s)} min={s.min():.3f} mean={s.mean():.3f} median={np.median(s):.3f} max={s.max():.3f} p95={np.percentile(s,95):.3f}")

# Confusion at default threshold
t_def = ens["threshold"]
pred_def = (proba >= t_def).astype(int)
tp = ((pred_def == 1) & (y_all == 1)).sum()
fp = ((pred_def == 1) & (y_all == 0)).sum()
tn = ((pred_def == 0) & (y_all == 0)).sum()
fn = ((pred_def == 0) & (y_all == 1)).sum()
print(f"\nAt default threshold ({t_def:.4f}):")
print(f"  TP={tp} FP={fp} TN={tn} FN={fn}")
print(f"  Precision={tp/(tp+fp+1e-8):.3f} Recall={tp/(tp+fn+1e-8):.3f}")
