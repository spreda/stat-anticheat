# %% [markdown]
# # CS2 Anti-Cheat — GPU Training (Google Colab)
#
# Paste this into a Colab notebook (Runtime → Change runtime type → **T4 GPU**).
# Downloads the full CS2CD dataset from HuggingFace, engineers features,
# and trains XGBoost + Isolation Forest on GPU.
#
# **Runtime**: ~10-15 min on T4 GPU (depends on download speed).
# **Storage**: ~3 GB temporary (auto-cleaned at end).

# %%
# ============================================================
# 1. INSTALL DEPENDENCIES
# ============================================================
!pip install -q huggingface_hub xgboost scikit-learn joblib pandas numpy pyarrow

import os, sys, json, time, warnings
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial

import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score, f1_score, classification_report,
    precision_recall_curve,
)
from sklearn.calibration import CalibratedClassifierCV
from huggingface_hub import snapshot_download

warnings.filterwarnings("ignore")
print(f"PyTorch/XGBoost GPU available: {xgb.build_info().get('USE_CUDA', False)}")
print(f"GPU device: {xgb.device() if hasattr(xgb, 'device') else 'check manually'}")

# %%
# ============================================================
# 2. DOWNLOAD DATASET FROM HUGGINGFACE
# ============================================================
HF_REPO = "CS2CD/CS2CD.Counter-Strike_2_Cheat_Detection"
DATA_DIR = Path("./cs2cd_dataset")

print(f"Downloading dataset from {HF_REPO}...")
t0 = time.time()
snapshot_download(
    repo_id=HF_REPO,
    repo_type="dataset",
    local_dir=str(DATA_DIR),
    local_dir_use_symlinks=False,
)
print(f"Downloaded in {time.time()-t0:.1f}s → {DATA_DIR}")

# Count files
for folder in ["no_cheater_present", "with_cheater_present"]:
    n = len(list((DATA_DIR / folder).glob("*.csv.gz")))
    print(f"  {folder}: {n} matches")

# %%
# ============================================================
# 3. FEATURE ENGINEERING (multiprocessing on CPU)
# ============================================================

def _load_match(folder_path: Path, idx: int):
    """Load csv.gz tick data and JSON events for a match."""
    import pandas as pd
    tick_df = pd.read_csv(str(folder_path / f"{idx}.csv.gz"), compression="gzip")
    with open(folder_path / f"{idx}.json", "r") as f:
        events = json.load(f)
    return tick_df, events


def _extract_json_features(events: dict) -> dict:
    features = {}
    for d in events.get("player_death", []):
        attacker = d.get("attacker_steamid")
        if attacker and attacker.startswith("Player_"):
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            features[attacker]["json_kills"] += 1
            if d.get("headshot", False):
                features[attacker]["json_headshots"] += 1
    for b in events.get("bullet_damage", []):
        attacker = b.get("attacker_steamid")
        if attacker and attacker.startswith("Player_"):
            if attacker not in features:
                features[attacker] = {"json_kills": 0, "json_headshots": 0, "json_wallbangs": 0}
            if b.get("num_penetrations", 0) > 0:
                features[attacker]["json_wallbangs"] += 1
    for v in features.values():
        v["json_headshot_ratio"] = v["json_headshots"] / max(v["json_kills"], 1)
    return features


def _process_one_match(args: tuple) -> list[dict] | None:
    """Process a single match file → list of player feature dicts."""
    folder_path_str, folder_name, match_label = args
    folder_path = Path(folder_path_str)

    # Find all csv.gz files in this folder
    csv_files = sorted(folder_path.glob("*.csv.gz"))
    results = []

    for csv_file in csv_files:
        idx = int(csv_file.stem)
        match_id = f"{folder_name}_{idx}"
        try:
            tick_df, events = _load_match(folder_path, idx)
        except Exception:
            continue

        # Cheater labels
        cheater_set = {c["steamid"] for c in events.get("cheaters", [])}
        tick_df.sort_values(["steamid", "tick"], inplace=True)

        # Aim features
        pitch_delta = tick_df.groupby("steamid")["pitch"].diff().abs()
        yaw_diff = tick_df.groupby("steamid")["yaw"].diff().abs()
        yaw_delta = np.where(yaw_diff > 180, 360 - yaw_diff, yaw_diff)
        mouse_mag = np.sqrt(
            tick_df["usercmd_mouse_dx"].fillna(0).values ** 2 +
            tick_df["usercmd_mouse_dy"].fillna(0).values ** 2
        )
        tick_df["pitch_delta"] = pitch_delta
        tick_df["yaw_delta"] = yaw_delta
        tick_df["mouse_mag"] = mouse_mag

        # Labels
        is_cheater = tick_df["steamid"].isin(cheater_set).astype(int).values
        tick_df["is_cheater"] = is_cheater
        if folder_name == "no_cheater_present":
            tick_df["label_confidence"] = 0.8
        else:
            tick_df["label_confidence"] = np.where(is_cheater == 1, 1.0, 0.9)

        # Single groupby
        agg_dict = {
            "pitch_delta": ["mean", "std"],
            "yaw_delta": ["mean", "std"],
            "mouse_mag": ["mean", "std"],
            "fov": "nunique",
            "is_scoped": "mean",
            "kills_total": "max",
            "deaths_total": "max",
            "headshot_kills_total": "max",
            "damage_total": "max",
            "total_rounds_played": "max",
            "ace_rounds_total": "max",
            "4k_rounds_total": "max",
            "3k_rounds_total": "max",
            "shots_fired": "max",
            "velocity": ["mean", "std", "max"],
            "is_airborne": "mean",
            "duck_amount": "mean",
            "is_walking": "mean",
            "fall_velo": "max",
            "FIRE": "mean",
            "RELOAD": "mean",
            "ZOOM": "mean",
            "is_cheater": "first",
            "label_confidence": "first",
        }
        available = set(tick_df.columns)
        agg_dict = {k: v for k, v in agg_dict.items() if k in available}

        agg = tick_df.groupby("steamid").agg(agg_dict)
        agg.columns = ["_".join(c).strip("_") for c in agg.columns]
        agg = agg.reset_index()

        rename_map = {
            "pitch_delta_mean": "aim_pitch_delta_mean",
            "pitch_delta_std": "aim_pitch_delta_std",
            "yaw_delta_mean": "aim_yaw_delta_mean",
            "yaw_delta_std": "aim_yaw_delta_std",
            "mouse_mag_mean": "aim_mouse_mag_mean",
            "mouse_mag_std": "aim_mouse_mag_std",
            "fov_nunique": "aim_fov_changes",
            "is_scoped_mean": "aim_scope_time_ratio",
            "kills_total_max": "combat_kills_total",
            "deaths_total_max": "combat_deaths_total",
            "headshot_kills_total_max": "combat_hs_total",
            "damage_total_max": "combat_damage_total",
            "total_rounds_played_max": "combat_rounds",
            "ace_rounds_total_max": "combat_ace_rounds",
            "4k_rounds_total_max": "combat_4k_rounds",
            "3k_rounds_total_max": "combat_3k_rounds",
            "shots_fired_max": "combat_shots_fired",
            "velocity_mean": "move_vel_mean",
            "velocity_std": "move_vel_std",
            "velocity_max": "move_vel_max",
            "is_airborne_mean": "move_airborne_ratio",
            "duck_amount_mean": "move_duck_mean",
            "is_walking_mean": "move_walk_ratio",
            "fall_velo_max": "move_fall_vel_max",
            "FIRE_mean": "btn_fire_rate",
            "RELOAD_mean": "btn_reload_rate",
            "ZOOM_mean": "btn_zoom_rate",
            "is_cheater_first": "is_cheater",
            "label_confidence_first": "label_confidence",
        }
        agg.rename(columns={k: v for k, v in rename_map.items() if k in agg.columns}, inplace=True)

        # Derived
        if "combat_kills_total" in agg and "combat_deaths_total" in agg:
            agg["combat_kdr"] = agg["combat_kills_total"] / agg["combat_deaths_total"].replace(0, 1)
        if "combat_hs_total" in agg and "combat_kills_total" in agg:
            agg["combat_headshot_ratio"] = agg["combat_hs_total"] / agg["combat_kills_total"].replace(0, 1)
        if "combat_damage_total" in agg and "combat_rounds" in agg:
            agg["combat_damage_per_round"] = agg["combat_damage_total"] / agg["combat_rounds"].replace(0, 1)
        if "combat_kills_total" in agg and "combat_rounds" in agg:
            agg["combat_kills_per_round"] = agg["combat_kills_total"] / agg["combat_rounds"].replace(0, 1)

        agg.drop(columns=[c for c in ["combat_kills_total", "combat_deaths_total", "combat_hs_total", "combat_damage_total", "combat_rounds"] if c in agg.columns], inplace=True)

        # JSON features
        jf = _extract_json_features(events)
        if jf:
            jdf = pd.DataFrame.from_dict(jf, orient="index").reset_index()
            jdf.rename(columns={"index": "steamid"}, inplace=True)
            agg = agg.merge(jdf, on="steamid", how="left")
        else:
            for col in ["json_kills", "json_headshots", "json_wallbangs", "json_headshot_ratio"]:
                agg[col] = 0

        agg.fillna(0, inplace=True)
        agg["match_id"] = match_id
        agg["match_label"] = match_label
        results.extend(agg.to_dict("records"))

    return results


# --- Run parallel feature extraction ---
import multiprocessing
N_WORKERS = min(multiprocessing.cpu_count(), 8)
print(f"\nFeature extraction with {N_WORKERS} workers...")

tasks = []
for folder, label in [("no_cheater_present", 0), ("with_cheater_present", 1)]:
    folder_path = DATA_DIR / folder
    tasks.append((str(folder_path), folder, label))

all_records = []
t0 = time.time()

# NOTE: on Colab, multiprocessing can be tricky. Use single-process if needed.
try:
    with ProcessPoolExecutor(max_workers=N_WORKERS) as executor:
        futures = [executor.submit(_process_one_match, t) for t in tasks]
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_records.extend(result)
except Exception as e:
    print(f"Multiprocessing failed ({e}), falling back to single process...")
    for t in tasks:
        result = _process_one_match(t)
        if result:
            all_records.extend(result)

df = pd.DataFrame.from_records(all_records)
elapsed = time.time() - t0
print(f"Done in {elapsed:.1f}s — {len(df)} player-records from {df['match_id'].nunique()} matches")
print(f"Class distribution: {df['is_cheater'].value_counts().to_dict()}")

# %%
# ============================================================
# 4. PREPARE DATA
# ============================================================
drop_cols = ["steamid", "match_id", "is_cheater", "match_label", "label_confidence"]
feature_cols = [c for c in df.columns if c not in drop_cols]

X = df[feature_cols].values.astype(np.float32)
y = df["is_cheater"].values.astype(np.int32)
weights = df["label_confidence"].values.astype(np.float32)

X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

print(f"Dataset: {X.shape[0]} samples, {X.shape[1]} features")
print(f"Class distribution: clean={np.sum(y==0)}, cheater={np.sum(y==1)}")

# %%
# ============================================================
# 5. TRAIN ON GPU
# ============================================================
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X).astype(np.float32)

# --- XGBoost on GPU ---
print("\n" + "="*50)
print("XGBOOST (GPU)")
print("="*50)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

xgb_model = xgb.XGBClassifier(
    n_estimators=300,
    max_depth=8,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=5,
    eval_metric="logloss",
    random_state=42,
    n_jobs=-1,
    tree_method="hist",
    device="cuda",
)

aucs = cross_val_score(xgb_model, X_scaled, y, cv=cv, scoring="roc_auc")
f1s = cross_val_score(xgb_model, X_scaled, y, cv=cv, scoring="f1")
print(f"  CV ROC-AUC: {aucs.mean():.4f} (+/- {aucs.std():.4f})")
print(f"  CV F1:      {f1s.mean():.4f} (+/- {f1s.std():.4f})")

# Fit on full data
xgb_model.fit(X_scaled, y, sample_weight=weights)

# Feature importance
importances = pd.Series(xgb_model.feature_importances_, index=feature_cols)
print(f"\n  Top 15 features:\n{importances.nlargest(15)}")

# --- Random Forest on GPU (cuML) or CPU ---
print("\n" + "="*50)
print("RANDOM FOREST (CPU — no cuML on Colab free tier)")
print("="*50)

rf_model = RandomForestClassifier(
    n_estimators=300, max_depth=14, class_weight="balanced",
    n_jobs=-1, random_state=42,
)
rf_aucs = cross_val_score(rf_model, X_scaled, y, cv=cv, scoring="roc_auc")
rf_f1s = cross_val_score(rf_model, X_scaled, y, cv=cv, scoring="f1")
print(f"  CV ROC-AUC: {rf_aucs.mean():.4f} (+/- {rf_aucs.std():.4f})")
print(f"  CV F1:      {rf_f1s.mean():.4f} (+/- {rf_f1s.std():.4f})")
rf_model.fit(X_scaled, y, sample_weight=weights)

# --- Calibrate best supervised model ---
best_name = "xgb" if aucs.mean() >= rf_aucs.mean() else "rf"
best_model = xgb_model if best_name == "xgb" else rf_model
print(f"\nBest supervised: {best_name} (AUC={max(aucs.mean(), rf_aucs.mean()):.4f})")

calibrated = CalibratedClassifierCV(best_model, method="isotonic", cv=5)
calibrated.fit(X_scaled, y, sample_weight=weights)

# Save supervised model
joblib.dump({
    "model": calibrated,
    "scaler": scaler,
    "feature_names": feature_cols,
    "best_model_name": best_name,
}, "supervised_v1.joblib")
print("Saved supervised_v1.joblib")

# --- Isolation Forest ---
print("\n" + "="*50)
print("ISOLATION FOREST")
print("="*50)

X_clean = X_scaled[y == 0]
iso = IsolationForest(n_estimators=300, contamination=0.1, random_state=42, n_jobs=-1)
iso.fit(X_clean)

scores = iso.decision_function(X_scaled)
risk_scores = (1 - (scores - scores.min()) / (scores.max() - scores.min())) * 100

iso_auc = roc_auc_score(y, risk_scores)
print(f"  Isolation Forest AUC: {iso_auc:.4f}")

joblib.dump({"model": iso, "risk_scores": risk_scores}, "isolation_forest_v1.joblib")
print("Saved isolation_forest_v1.joblib")

# %%
# ============================================================
# 6. ENSEMBLE
# ============================================================
print("\n" + "="*50)
print("ENSEMBLE")
print("="*50)

sup_proba = calibrated.predict_proba(X_scaled)[:, 1]
base_risk = risk_scores / 100.0

best_auc, best_w = 0, 0.5
for w in np.arange(0.1, 1.0, 0.05):
    ens = w * sup_proba + (1 - w) * base_risk
    auc = roc_auc_score(y, ens)
    if auc > best_auc:
        best_auc, best_w = auc, w

ensemble_scores = best_w * sup_proba + (1 - best_w) * base_risk
print(f"Best weight: supervised={best_w:.2f}, anomaly={1-best_w:.2f}")
print(f"Ensemble AUC: {best_auc:.4f}")

# Threshold
precisions, recalls, thresholds = precision_recall_curve(y, ensemble_scores)
f1_arr = 2 * (precisions * recalls) / (precisions + recalls + 1e-8)
best_idx = np.argmax(f1_arr)
best_thresh = thresholds[best_idx] if best_idx < len(thresholds) else 0.5
print(f"Best threshold (F1): {best_thresh:.3f}, F1={f1_arr[best_idx]:.4f}")

preds = (ensemble_scores >= best_thresh).astype(int)
print(f"\nClassification Report (threshold={best_thresh:.3f}):")
print(classification_report(y, preds, target_names=["clean", "cheater"]))

joblib.dump({
    "supervised_weight": best_w,
    "anomaly_weight": 1 - best_w,
    "threshold": best_thresh,
    "scaler": scaler,
    "feature_names": feature_cols,
}, "ensemble_config_v1.joblib")
print("Saved ensemble_config_v1.joblib")

# %%
# ============================================================
# 7. DOWNLOAD MODELS
# ============================================================
print("\n" + "="*50)
print("COMPLETE — Download model files:")
print("  supervised_v1.joblib")
print("  isolation_forest_v1.joblib")
print("  ensemble_config_v1.joblib")
print("="*50)

# In Colab, use:
# from google.colab import files
# files.download("supervised_v1.joblib")
# files.download("isolation_forest_v1.joblib")
# files.download("ensemble_config_v1.joblib")
