"""
Quick demo training on 20 files. Run full training later with train_subset.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, classification_report, precision_recall_curve
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb
import joblib

from ml.features import build_dataset

BASE = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset")
MODELS_DIR = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\models")
MODELS_DIR.mkdir(exist_ok=True)


def main():
    print("Building demo dataset (20 files)...")
    df = build_dataset(BASE, max_files=10)
    print(f"Dataset: {len(df)} records, {df['is_cheater'].sum()} cheaters")

    drop_cols = ["steamid", "match_id", "is_cheater", "match_label", "label_confidence"]
    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols].values
    y = df["is_cheater"].values
    weights = df["label_confidence"].values

    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print(f"Class distribution: {np.bincount(y)}")

    model = xgb.XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, scale_pos_weight=5, eval_metric="logloss", random_state=42, n_jobs=-1)
    model.fit(X_scaled, y, sample_weight=weights)

    calibrated = CalibratedClassifierCV(model, method="isotonic", cv=3)
    calibrated.fit(X_scaled, y, sample_weight=weights)

    proba = calibrated.predict_proba(X_scaled)[:, 1]
    auc = roc_auc_score(y, proba)
    print(f"AUC: {auc:.4f}")

    prec, rec, thresh = precision_recall_curve(y, proba)
    f1s = 2 * (prec * rec) / (prec + rec + 1e-8)
    best_idx = np.argmax(f1s)
    best_thresh = thresh[best_idx] if best_idx < len(thresh) else 0.5
    print(f"Threshold: {best_thresh:.3f}, F1={f1s[best_idx]:.4f}")

    preds = (proba >= best_thresh).astype(int)
    print(classification_report(y, preds, target_names=["clean", "cheater"]))

    joblib.dump({
        "model": calibrated,
        "scaler": scaler,
        "feature_names": feature_cols,
        "threshold": best_thresh,
    }, MODELS_DIR / "model_v1.joblib")
    print(f"Saved to {MODELS_DIR / 'model_v1.joblib'}")

    importances = pd.Series(model.feature_importances_, index=feature_cols)
    print(f"Top features:\n{importances.nlargest(10)}")


if __name__ == "__main__":
    main()
