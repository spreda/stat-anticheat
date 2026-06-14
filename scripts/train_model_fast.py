"""
Fast training script — uses multiprocessing for dataset building.
Usage: python scripts/train_model_fast.py [n_workers]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, classification_report, precision_recall_curve
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb
import joblib

from ml.features_fast import build_dataset_fast

BASE = Path(r"C:\Users\1\Documents\dev\repos\indi\anticheat\datasets\cs2cd_dataset")
MODELS_DIR = Path(r"C:\Users\1\Documents\dev\repos\indi\anticheat\models")
MODELS_DIR.mkdir(exist_ok=True)


def prepare_data(df: pd.DataFrame):
    drop_cols = ["steamid", "match_id", "is_cheater", "match_label", "label_confidence"]
    feature_cols = [c for c in df.columns if c not in drop_cols]
    X = df[feature_cols].values
    y = df["is_cheater"].values
    weights = df["label_confidence"].values
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
    return X, y, weights, feature_cols


def main():
    print("=" * 60)
    print("FAST TRAINING (sequential + streaming)")
    print("=" * 60, flush=True)

    t0 = time.time()
    df = build_dataset_fast(BASE, max_files=None)
    build_time = time.time() - t0
    print(f"\nDataset built in {build_time:.1f}s: {len(df)} records, {df['match_id'].nunique()} matches", flush=True)

    X, y, weights, feature_names = prepare_data(df)
    print(f"Features: {len(feature_names)}, samples: {len(y)}, cheaters: {int(y.sum())}", flush=True)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # --- XGBoost (GPU if available, else CPU) ---
    print("\n--- XGBoost ---", flush=True)
    try:
        import subprocess
        subprocess.check_output(["nvidia-smi"], timeout=5)
        tree_method, device = "hist", "cuda"
        print("  Using GPU (CUDA)", flush=True)
    except Exception:
        tree_method, device = "hist", "cpu"
        print("  Using CPU (no GPU found)", flush=True)

    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=8, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, scale_pos_weight=5,
        eval_metric="logloss", random_state=42, n_jobs=-1,
        tree_method=tree_method, device=device,
    )
    aucs = cross_val_score(xgb_model, X_scaled, y, cv=cv, scoring="roc_auc")
    f1s = cross_val_score(xgb_model, X_scaled, y, cv=cv, scoring="f1")
    print(f"  CV ROC-AUC: {aucs.mean():.4f} (+/- {aucs.std():.4f})", flush=True)
    print(f"  CV F1:      {f1s.mean():.4f} (+/- {f1s.std():.4f})", flush=True)
    xgb_model.fit(X_scaled, y, sample_weight=weights)

    # --- Random Forest ---
    print("\n--- Random Forest ---", flush=True)
    rf_model = RandomForestClassifier(
        n_estimators=300, max_depth=14, class_weight="balanced",
        n_jobs=-1, random_state=42,
    )
    rf_aucs = cross_val_score(rf_model, X_scaled, y, cv=cv, scoring="roc_auc")
    rf_f1s = cross_val_score(rf_model, X_scaled, y, cv=cv, scoring="f1")
    print(f"  CV ROC-AUC: {rf_aucs.mean():.4f} (+/- {rf_aucs.std():.4f})", flush=True)
    print(f"  CV F1:      {rf_f1s.mean():.4f} (+/- {rf_f1s.std():.4f})", flush=True)
    rf_model.fit(X_scaled, y, sample_weight=weights)

    # --- Best supervised ---
    best_name = "xgb" if aucs.mean() >= rf_aucs.mean() else "rf"
    best_model = xgb_model if best_name == "xgb" else rf_model
    print(f"\nBest supervised: {best_name}", flush=True)

    calibrated = CalibratedClassifierCV(best_model, method="isotonic", cv=5)
    calibrated.fit(X_scaled, y, sample_weight=weights)
    joblib.dump({
        "model": calibrated, "scaler": scaler,
        "feature_names": feature_names, "best_model_name": best_name,
    }, MODELS_DIR / "supervised_v1.joblib")
    print(f"Saved supervised_v1.joblib", flush=True)

    # --- Isolation Forest ---
    print("\n--- Isolation Forest ---", flush=True)
    X_clean = X_scaled[y == 0]
    iso = IsolationForest(n_estimators=300, contamination=0.1, random_state=42, n_jobs=-1)
    iso.fit(X_clean)
    scores = iso.decision_function(X_scaled)
    risk_scores = (1 - (scores - scores.min()) / (scores.max() - scores.min())) * 100
    iso_auc = roc_auc_score(y, risk_scores)
    print(f"  AUC: {iso_auc:.4f}", flush=True)
    joblib.dump({"model": iso, "risk_scores": risk_scores}, MODELS_DIR / "isolation_forest_v1.joblib")
    print(f"Saved isolation_forest_v1.joblib", flush=True)

    # --- Ensemble ---
    print("\n--- Ensemble ---", flush=True)
    sup_proba = calibrated.predict_proba(X_scaled)[:, 1]
    base_risk = risk_scores / 100.0

    best_auc, best_w = 0, 0.5
    for w in np.arange(0.1, 1.0, 0.05):
        ens = w * sup_proba + (1 - w) * base_risk
        auc = roc_auc_score(y, ens)
        if auc > best_auc:
            best_auc, best_w = auc, w

    ensemble_scores = best_w * sup_proba + (1 - best_w) * base_risk
    print(f"  Weight: sup={best_w:.2f}, anomaly={1-best_w:.2f}", flush=True)
    print(f"  Ensemble AUC: {best_auc:.4f}", flush=True)

    precisions, recalls, thresholds = precision_recall_curve(y, ensemble_scores)
    f1_arr = 2 * (precisions * recalls) / (precisions + recalls + 1e-8)
    best_idx = np.argmax(f1_arr)
    best_thresh = thresholds[best_idx] if best_idx < len(thresholds) else 0.5
    print(f"  Threshold: {best_thresh:.3f}, F1: {f1_arr[best_idx]:.4f}", flush=True)

    preds = (ensemble_scores >= best_thresh).astype(int)
    print(f"\nClassification Report:", flush=True)
    print(classification_report(y, preds, target_names=["clean", "cheater"]), flush=True)

    joblib.dump({
        "supervised_weight": best_w, "anomaly_weight": 1 - best_w,
        "threshold": best_thresh, "scaler": scaler, "feature_names": feature_names,
    }, MODELS_DIR / "ensemble_config_v1.joblib")

    total = time.time() - t0
    print(f"\n{'='*60}", flush=True)
    print(f"TOTAL TIME: {total:.1f}s ({total/60:.1f} min)", flush=True)
    print(f"  Dataset build: {build_time:.1f}s", flush=True)
    print(f"  Training:      {total - build_time:.1f}s", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
