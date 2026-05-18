"""
Train baseline ML models for CS2 anti-cheat.
Usage: python scripts/train_model.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import pandas as pd
import numpy as np
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, classification_report
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb
import joblib

from ml.features import build_dataset

BASE = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset")
MODELS_DIR = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\models")
MODELS_DIR.mkdir(exist_ok=True)


def prepare_data(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Prepare feature matrix, target, and sample weights from built dataset."""
    # Drop non-feature columns
    drop_cols = ["steamid", "match_id", "is_cheater", "match_label", "label_confidence"]
    feature_cols = [c for c in df.columns if c not in drop_cols]

    X = df[feature_cols].values
    y = df["is_cheater"].values
    weights = df["label_confidence"].values  # sample weights for noisy labels

    # Handle inf/nan
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    return X, y, weights, feature_cols


def train_supervised(X: np.ndarray, y: np.ndarray, weights: np.ndarray, feature_names: list[str]) -> dict:
    """Train and evaluate supervised models with cross-validation."""
    print(f"\nDataset: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"Class distribution: {np.bincount(y)}")

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Class weights for imbalance
    cw = "balanced"

    models = {
        "rf": RandomForestClassifier(n_estimators=200, max_depth=12, class_weight=cw, n_jobs=-1, random_state=42),
        "xgb": xgb.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.1,
            scale_pos_weight=5, eval_metric="logloss", random_state=42, n_jobs=-1
        ),
    }

    results = {}
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    for name, model in models.items():
        print(f"\n--- {name.upper()} ---")
        aucs = cross_val_score(model, X_scaled, y, cv=cv, scoring="roc_auc")
        f1s = cross_val_score(model, X_scaled, y, cv=cv, scoring="f1")
        print(f"  CV ROC-AUC: {aucs.mean():.4f} (+/- {aucs.std():.4f})")
        print(f"  CV F1:      {f1s.mean():.4f} (+/- {f1s.std():.4f})")

        # Fit on full data for feature importance (with sample weights)
        model.fit(X_scaled, y, sample_weight=weights)
        results[name] = {
            "model": model,
            "auc_mean": aucs.mean(),
            "f1_mean": f1s.mean(),
        }

        if hasattr(model, "feature_importances_"):
            importances = pd.Series(model.feature_importances_, index=feature_names)
            print(f"  Top features:\n{importances.nlargest(10)}")

    # Calibrate best model (XGB usually wins)
    best_name = max(results, key=lambda k: results[k]["auc_mean"])
    print(f"\nBest model: {best_name} (AUC={results[best_name]['auc_mean']:.4f})")

    best_model = results[best_name]["model"]
    calibrated = CalibratedClassifierCV(best_model, method="isotonic", cv=5)
    calibrated.fit(X_scaled, y, sample_weight=weights)

    # Save artifacts
    joblib.dump({
        "model": calibrated,
        "scaler": scaler,
        "feature_names": feature_names,
        "best_model_name": best_name,
    }, MODELS_DIR / "supervised_v1.joblib")
    print(f"Saved supervised model to {MODELS_DIR / 'supervised_v1.joblib'}")

    return results


def train_baseline(X: np.ndarray, y: np.ndarray) -> dict:
    """Train Isolation Forest for anomaly detection on clean players."""
    print("\n--- Isolation Forest (anomaly detection) ---")

    # Train only on clean players (label=0)
    X_clean = X[y == 0]
    iso = IsolationForest(n_estimators=200, contamination=0.1, random_state=42, n_jobs=-1)
    iso.fit(X_clean)

    # Score all samples (lower = more anomalous)
    scores = iso.decision_function(X)
    # Convert to [0, 100] risk score (higher = more suspicious)
    risk_scores = (1 - (scores - scores.min()) / (scores.max() - scores.min())) * 100

    auc = roc_auc_score(y, risk_scores)
    print(f"  Isolation Forest AUC: {auc:.4f}")

    joblib.dump({
        "model": iso,
        "risk_scores": risk_scores,
    }, MODELS_DIR / "isolation_forest_v1.joblib")
    print(f"Saved isolation forest to {MODELS_DIR / 'isolation_forest_v1.joblib'}")

    return {"iso": iso, "auc": auc}


def train_ensemble(X: np.ndarray, y: np.ndarray, weights: np.ndarray, feature_names: list[str]) -> dict:
    """Train weighted ensemble of supervised + anomaly models."""
    print("\n=== ENSEMBLE TRAINING ===")

    sup_results = train_supervised(X, y, weights, feature_names)
    base_results = train_baseline(X, y)

    # Load saved models
    sup_artifact = joblib.load(MODELS_DIR / "supervised_v1.joblib")
    base_artifact = joblib.load(MODELS_DIR / "isolation_forest_v1.joblib")

    scaler = sup_artifact["scaler"]
    X_scaled = scaler.transform(X)

    sup_proba = sup_artifact["model"].predict_proba(X_scaled)[:, 1]
    base_risk = base_artifact["risk_scores"] / 100.0  # Normalize to [0,1]

    # Weighted ensemble (tune weights via grid search)
    best_auc = 0
    best_w = 0.5
    for w in np.arange(0.1, 1.0, 0.1):
        ensemble = w * sup_proba + (1 - w) * base_risk
        auc = roc_auc_score(y, ensemble)
        if auc > best_auc:
            best_auc = auc
            best_w = w

    ensemble_scores = best_w * sup_proba + (1 - best_w) * base_risk
    print(f"\nBest ensemble weight: supervised={best_w:.2f}, anomaly={1-best_w:.2f}")
    print(f"Ensemble AUC: {best_auc:.4f}")

    # Threshold for classification
    from sklearn.metrics import precision_recall_curve
    precisions, recalls, thresholds = precision_recall_curve(y, ensemble_scores)
    f1s = 2 * (precisions * recalls) / (precisions + recalls + 1e-8)
    best_thresh_idx = np.argmax(f1s)
    best_thresh = thresholds[best_thresh_idx] if best_thresh_idx < len(thresholds) else 0.5
    print(f"Best threshold (F1): {best_thresh:.3f}, F1={f1s[best_thresh_idx]:.4f}")

    # Final report
    preds = (ensemble_scores >= best_thresh).astype(int)
    print(f"\nClassification Report (threshold={best_thresh:.3f}):")
    print(classification_report(y, preds, target_names=["clean", "cheater"]))

    # Save ensemble config
    joblib.dump({
        "supervised_weight": best_w,
        "anomaly_weight": 1 - best_w,
        "threshold": best_thresh,
        "scaler": scaler,
        "feature_names": feature_names,
    }, MODELS_DIR / "ensemble_config_v1.joblib")
    print(f"Saved ensemble config to {MODELS_DIR / 'ensemble_config_v1.joblib'}")

    return {
        "ensemble_scores": ensemble_scores,
        "best_weight": best_w,
        "best_threshold": best_thresh,
        "auc": best_auc,
    }


def main():
    print("Building dataset...")
    # Use subset for faster iteration during development
    df = build_dataset(BASE, max_files=None)
    print(f"Built dataset: {len(df)} player-records from {df['match_id'].nunique()} matches")

    X, y, weights, feature_names = prepare_data(df)
    train_ensemble(X, y, weights, feature_names)
    print("\nTraining complete.")


if __name__ == "__main__":
    main()
