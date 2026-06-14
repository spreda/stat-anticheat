"""Quick test: fast vs original on 5 files."""
import sys, time
import numpy as np
import pandas as pd

def main():
    sys.path.insert(0, "app")
    from pathlib import Path
    from ml.features_fast import build_dataset_parallel
    from ml.features import build_dataset

    BASE = Path("datasets/cs2cd_dataset")

    # --- Fast version on 5 files ---
    print("=== FAST VERSION (5 files) ===", flush=True)
    t0 = time.time()
    df_fast = build_dataset_parallel(BASE, max_files=5, n_workers=4)
    t_fast = time.time() - t0
    print(f"Time: {t_fast:.1f}s, records: {len(df_fast)}", flush=True)
    print(f"Columns: {sorted(df_fast.columns.tolist())}", flush=True)
    print(f"Matches: {df_fast['match_id'].nunique()}", flush=True)
    print(flush=True)

    # --- Original version on 5 files ---
    print("=== ORIGINAL VERSION (5 files) ===", flush=True)
    t0 = time.time()
    df_orig = build_dataset(BASE, max_files=5)
    t_orig = time.time() - t0
    print(f"Time: {t_orig:.1f}s, records: {len(df_orig)}", flush=True)
    print(f"Columns: {sorted(df_orig.columns.tolist())}", flush=True)
    print(f"Matches: {df_orig['match_id'].nunique()}", flush=True)
    print(flush=True)

    # --- Compare ---
    print("=== COMPARISON ===", flush=True)
    fast_cols = set(df_fast.columns)
    orig_cols = set(df_orig.columns)
    print(f"Fast extra: {fast_cols - orig_cols}", flush=True)
    print(f"Orig extra: {orig_cols - fast_cols}", flush=True)
    common = fast_cols & orig_cols
    print(f"Common: {len(common)} columns", flush=True)
    print(f"Fast players: {len(df_fast)}, Orig players: {len(df_orig)}", flush=True)
    print(f"Speedup: {t_orig/t_fast:.1f}x", flush=True)

    # Sort both by match_id + steamid for positional comparison
    df_fast_sorted = df_fast.sort_values(["match_id", "steamid"]).reset_index(drop=True)
    df_orig_sorted = df_orig.sort_values(["match_id", "steamid"]).reset_index(drop=True)

    # Compare numeric values for common columns
    all_ok = True
    for col in sorted(common):
        if col in ("match_id", "steamid"):
            continue
        v_fast = pd.to_numeric(df_fast_sorted[col], errors="coerce").values.astype(float)
        v_orig = pd.to_numeric(df_orig_sorted[col], errors="coerce").values.astype(float)
        if len(v_fast) == len(v_orig):
            mask = ~(np.isnan(v_fast) | np.isnan(v_orig))
            if np.allclose(v_fast[mask], v_orig[mask], equal_nan=True, atol=1e-3):
                status = "OK"
            else:
                diff = np.abs(v_fast[mask] - v_orig[mask])
                status = f"DIFF max={diff.max():.6f}"
                all_ok = False
        else:
            status = f"LEN MISMATCH {len(v_fast)} vs {len(v_orig)}"
            all_ok = False
        print(f"  {col}: {status}", flush=True)

    print(f"\n{'ALL OK' if all_ok else 'SOME DIFFERENCES FOUND'}", flush=True)

if __name__ == "__main__":
    main()
