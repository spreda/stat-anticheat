"""
EDA script for CS2CD dataset.
Run: python scripts/eda.py
"""
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from pathlib import Path
import json

BASE = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\datasets\cs2cd_dataset")
OUT = Path(r"C:\Users\1\Documents\Dev\repos\indi\anticheat\notebooks\eda_outputs")
OUT.mkdir(parents=True, exist_ok=True)


def load_match(folder: str, idx: int) -> tuple[pd.DataFrame, dict]:
    """Load parquet tick data and JSON events for a match."""
    tick_df = pd.read_parquet(BASE / folder / f"{idx}.parquet")
    with open(BASE / folder / f"{idx}.json", "r") as f:
        events = json.load(f)
    return tick_df, events


def inspect_schema(df: pd.DataFrame, title: str):
    print(f"\n{'='*60}")
    print(title)
    print(f"{'='*60}")
    print(f"Shape: {df.shape}")
    print(f"Columns ({len(df.columns)}): {list(df.columns)}")
    print(f"Dtypes:\n{df.dtypes}")
    print(f"Missing: {df.isnull().sum().sum()} total")
    print(f"Sample:\n{df.head(3).T}")


def check_granularity(df: pd.DataFrame):
    print(f"\n--- Granularity ---")
    print(f"Unique steamids: {df['steamid'].nunique()}")
    print(f"Unique entity_ids: {df['entity_id'].nunique()}")
    print(f"Total rows: {len(df)}")
    if 'total_rounds_played' in df.columns:
        print(f"Rounds: {df['total_rounds_played'].max()}")


def get_cheater_set(events: dict) -> set:
    """Extract cheater steamids from JSON events."""
    cheaters = events.get("cheaters", [])
    return {c["steamid"] for c in cheaters}


def label_players(df: pd.DataFrame, cheater_set: set) -> pd.DataFrame:
    """Add per-player cheater label based on JSON metadata."""
    df = df.copy()
    df["is_cheater"] = df["steamid"].isin(cheater_set).astype(int)
    return df


def aggregate_player_match(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate tick-level data to player-match level."""
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    group_cols = ["steamid", "is_cheater"]
    if "team_num" in df.columns:
        group_cols.append("team_num")

    agg = {}
    for col in numeric:
        if col not in group_cols and not col.startswith("is_cheater"):
            agg[col] = ["mean", "std", "max"]

    grouped = df.groupby(group_cols).agg(agg)
    grouped.columns = ["_".join(col).strip() for col in grouped.columns.values]
    return grouped.reset_index()


def quick_compare(clean_dfs: list[pd.DataFrame], cheat_dfs: list[pd.DataFrame]):
    """Compare aggregated features between classes."""
    clean_agg = pd.concat([aggregate_player_match(df) for df in clean_dfs])
    cheat_agg = pd.concat([aggregate_player_match(df) for df in cheat_dfs])

    print(f"\n--- Aggregation Stats ---")
    print(f"Clean player-records: {len(clean_agg)}")
    print(f"Cheat player-records: {len(cheat_agg)}")
    print(f"Cheaters in cheat set: {cheat_agg['is_cheater'].sum()}")
    print(f"Clean in cheat set: {len(cheat_agg) - cheat_agg['is_cheater'].sum()}")

    common = clean_agg.columns.intersection(cheat_agg.columns)
    common = [c for c in common if c not in ["steamid", "is_cheater", "team_num"]]

    diffs = []
    for col in common[:30]:
        c_mean = clean_agg[col].mean()
        ch_mean = cheat_agg[col].mean()
        diff_pct = (ch_mean - c_mean) / abs(c_mean) * 100 if c_mean != 0 else 0
        diffs.append((col, c_mean, ch_mean, diff_pct))

    diffs.sort(key=lambda x: abs(x[3]), reverse=True)
    print(f"\n--- Top Feature Differences (cheat vs clean %) ---")
    for col, c, ch, pct in diffs[:15]:
        print(f"  {col:45s}  clean={c:.4f}  cheat={ch:.4f}  diff={pct:+.1f}%")

    return clean_agg, cheat_agg


def row_count_stats():
    print(f"\n--- Row Count Distribution ---")
    for folder, name in [("no_cheater_present", "Clean"), ("with_cheater_present", "Cheat")]:
        files = sorted((BASE / folder).glob("*.parquet"))
        rows = [pq.ParquetFile(f).metadata.num_rows for f in files]
        print(f"{name}: n={len(rows)}, min={min(rows):,}, max={max(rows):,}, mean={sum(rows)//len(rows):,}")


def main():
    print("Loading samples...")
    clean_tick, clean_events = load_match("no_cheater_present", 0)
    cheat_tick, cheat_events = load_match("with_cheater_present", 0)

    inspect_schema(clean_tick, "CLEAN SAMPLE (0.parquet)")
    check_granularity(clean_tick)

    inspect_schema(cheat_tick, "CHEAT SAMPLE (0.parquet)")
    check_granularity(cheat_tick)

    # Check cheater labels
    clean_cheaters = get_cheater_set(clean_events)
    cheat_cheaters = get_cheater_set(cheat_events)
    print(f"\n--- Cheater Labels ---")
    print(f"Clean match cheaters: {clean_cheaters}")
    print(f"Cheat match cheaters: {cheat_cheaters}")

    # Label and aggregate
    clean_tick = label_players(clean_tick, clean_cheaters)
    cheat_tick = label_players(cheat_tick, cheat_cheaters)

    # Load a few more for comparison
    clean_ticks = [clean_tick]
    cheat_ticks = [cheat_tick]
    for i in range(1, 3):
        ct, ce = load_match("no_cheater_present", i)
        ct = label_players(ct, get_cheater_set(ce))
        clean_ticks.append(ct)

        ch, che = load_match("with_cheater_present", i)
        ch = label_players(ch, get_cheater_set(che))
        cheat_ticks.append(ch)

    row_count_stats()

    print("\nAggregating and comparing...")
    clean_agg, cheat_agg = quick_compare(clean_ticks, cheat_ticks)

    clean_agg.head(20).to_csv(OUT / "clean_agg_sample.csv", index=False)
    cheat_agg.head(20).to_csv(OUT / "cheat_agg_sample.csv", index=False)
    print(f"\nSaved sample aggregations to {OUT}")

    print("\nEDA complete.")


if __name__ == "__main__":
    main()
