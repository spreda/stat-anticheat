"""Evaluate ensemble model on the full dataset: AUC-ROC, threshold sweep, per-match accuracy."""
import warnings
warnings.filterwarnings("ignore")

import sys, os, json, time
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import roc_auc_score, precision_recall_curve, f1_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from ml.features import build_features

# ── Load models ──────────────────────────────────────────────────────────────
MODELS = os.path.join(os.path.dirname(__file__), "..", "models")
ens = joblib.load(os.path.join(MODELS, "ensemble_config_v1.joblib"))
sup_art = joblib.load(os.path.join(MODELS, "supervised_v1.joblib"))
iso_art = joblib.load(os.path.join(MODELS, "isolation_forest_v1.joblib"))
sup = sup_art["model"] if isinstance(sup_art, dict) else sup_art
iso = iso_art["model"] if isinstance(iso_art, dict) else iso_art

fnames = ens["feature_names"]
scaler = ens["scaler"]
ws = float(ens["supervised_weight"])
wa = float(ens["anomaly_weight"])

print(f"Ensemble: supervised={ws:.2f}, anomaly={wa:.2f}, threshold={ens['threshold']:.4f}")
print(f"Features: {len(fnames)}")

# ── Collect dataset files ────────────────────────────────────────────────────
DS = os.path.join(os.path.dirname(__file__), "..", "datasets", "cs2cd_dataset")
rows = []
for label, subdir in [(1, "with_cheater_present"), (0, "no_cheater_present")]:
    d = os.path.join(DS, subdir)
    for f in os.listdir(d):
        if f.endswith(".parquet"):
            rows.append((os.path.join(d, f), label))

print(f"Total matches: {len(rows)}")

# ── Extract features for ALL matches ─────────────────────────────────────────
X_all, y_all, match_labels = [], [], []
t0 = time.time()
errors = 0

for idx, (fp, label) in enumerate(rows):
    try:
        tick = pd.read_parquet(fp)
        jf = fp.replace(".parquet", ".json")
        events = json.load(open(jf)) if os.path.exists(jf) else {}
        dname = os.path.basename(os.path.dirname(fp))
        feats = build_features(tick, events, dname)
        X = feats[fnames].values
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        X_all.append(X)
        y_all.extend([label] * len(X))
        match_labels.extend([(fp, label)] * len(X))
    except Exception as e:
        errors += 1

    if (idx + 1) % 100 == 0:
        elapsed = time.time() - t0
        eta = elapsed / (idx + 1) * (len(rows) - idx - 1)
        print(f"  {idx+1}/{len(rows)} errors={errors} elapsed={elapsed:.0f}s eta={eta:.0f}s")

elapsed = time.time() - t0
print(f"\nDone: {len(rows)} matches in {elapsed:.0f}s, {errors} errors")

X_all = np.vstack(X_all)
y_all = np.array(y_all)
print(f"Total player-samples: {len(y_all)}")
print(f"  Cheater: {y_all.sum()} ({y_all.mean()*100:.1f}%)")
print(f"  Clean:   {(y_all==0).sum()} ({(1-y_all.mean())*100:.1f}%)")

# ── Score ────────────────────────────────────────────────────────────────────
X_sc = scaler.transform(X_all)
sup_p = sup.predict_proba(X_sc)[:, 1]
iso_s = iso.decision_function(X_sc)
iso_r = 1 - (iso_s - iso_s.min()) / (iso_s.max() - iso_s.min() + 1e-8)
proba = ws * sup_p + wa * iso_r

# ── AUC-ROC ──────────────────────────────────────────────────────────────────
auc = roc_auc_score(y_all, proba)
print(f"\n{'='*60}")
print(f"AUC-ROC: {auc:.4f}")
print(f"{'='*60}")

# ── Threshold sweep ──────────────────────────────────────────────────────────
print(f"\n{'Threshold sweep':^60}")
print(f"{'─'*60}")
print(f"{'t':>5} {'Prec':>6} {'Rec':>6} {'F1':>6} {'TP':>5} {'FP':>5} {'TN':>5} {'FN':>5} {'Acc':>6}")
print(f"{'─'*60}")

best_f1 = 0
best_t = 0
for t in np.arange(0.30, 0.82, 0.02):
    pred = (proba >= t).astype(int)
    tp = ((pred == 1) & (y_all == 1)).sum()
    fp = ((pred == 1) & (y_all == 0)).sum()
    tn = ((pred == 0) & (y_all == 0)).sum()
    fn = ((pred == 0) & (y_all == 1)).sum()
    prec = tp / (tp + fp + 1e-8)
    rec = tp / (tp + fn + 1e-8)
    f1 = 2 * prec * rec / (prec + rec + 1e-8)
    acc = (tp + tn) / len(y_all)
    marker = ""
    if f1 > best_f1:
        best_f1 = f1
        best_t = t
    print(f"{t:5.2f} {prec:6.3f} {rec:6.3f} {f1:6.3f} {tp:5d} {fp:5d} {tn:5d} {fn:5d} {acc:6.3f}")

print(f"{'─'*60}")
print(f"Best F1={best_f1:.3f} at threshold={best_t:.2f}")

# ── Confusion matrix at default threshold ────────────────────────────────────
t_def = ens["threshold"]
pred_def = (proba >= t_def).astype(int)
tp = ((pred_def == 1) & (y_all == 1)).sum()
fp = ((pred_def == 1) & (y_all == 0)).sum()
tn = ((pred_def == 0) & (y_all == 0)).sum()
fn = ((pred_def == 0) & (y_all == 1)).sum()
prec = tp / (tp + fp + 1e-8)
rec = tp / (tp + fn + 1e-8)
f1 = 2 * prec * rec / (prec + rec + 1e-8)
acc = (tp + tn) / len(y_all)

print(f"\nConfusion matrix at default threshold ({t_def:.4f}):")
print(f"                Predicted")
print(f"                Clean   Cheater")
print(f"  Actual Clean   {tn:5d}   {fp:5d}")
print(f"  Actual Cheater {fn:5d}   {tp:5d}")
print(f"  Precision: {prec:.4f}")
print(f"  Recall:    {rec:.4f}")
print(f"  F1:        {f1:.4f}")
print(f"  Accuracy:  {acc:.4f}")

# ── Per-match accuracy (does model flag ANY player in cheater matches?) ──────
print(f"\n{'Per-match analysis':^60}")
print(f"{'─'*60}")
match_data = {}
for i, (fp, label) in enumerate(match_labels):
    if fp not in match_data:
        match_data[fp] = {"label": label, "scores": []}
    match_data[fp]["scores"].append(proba[i])

tp_m, fp_m, tn_m, fn_m = 0, 0, 0, 0
for fp, md in match_data.items():
    max_score = max(md["scores"])
    predicted = 1 if max_score >= t_def else 0
    actual = md["label"]
    if predicted == 1 and actual == 1:
        tp_m += 1
    elif predicted == 1 and actual == 0:
        fp_m += 1
    elif predicted == 0 and actual == 0:
        tn_m += 1
    else:
        fn_m += 1

print(f"Match-level (flag if ANY player exceeds threshold):")
print(f"  Correct cheater matches flagged:   {tp_m}/{tp_m+fn_m} ({tp_m/(tp_m+fn_m+1e-8)*100:.1f}%)")
print(f"  Clean matches incorrectly flagged: {fp_m}/{fp_m+tn_m} ({fp_m/(fp_m+tn_m+1e-8)*100:.1f}%)")
print(f"  Overall match accuracy: {(tp_m+tn_m)/(tp_m+fp_m+tn_m+fn_m)*100:.1f}%")

# ── Score distribution ──────────────────────────────────────────────────────
print(f"\nScore distribution:")
for label_name, label_val in [("Clean", 0), ("Cheater", 1)]:
    scores = proba[y_all == label_val]
    print(f"  {label_name}: min={scores.min():.3f} mean={scores.mean():.3f} median={np.median(scores):.3f} max={scores.max():.3f} p95={np.percentile(scores,95):.3f}")
