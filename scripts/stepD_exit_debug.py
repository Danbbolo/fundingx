"""
Debug: verify T+10s vs T+1min use DIFFERENT timestamps and produce DIFFERENT fills.
Check 5 specific settlements.
"""
import io
import os
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import pyarrow.parquet as pq
import requests
import zstandard as zstd

CHFD_BASE = "https://api.cryptohftdata.com"
CHFD_KEY = os.environ.get("CRYPTOHFTDATA_API_KEY", "")
SYMBOL = "LABUSDT"

DEBUG_SETTLEMENTS = [
    "2026-06-24T12:00:00.012000+00:00",
    "2026-06-27T17:00:00+00:00",
    "2026-06-30T08:00:00+00:00",
    "2026-07-02T21:00:00+00:00",
    "2026-07-03T02:00:00+00:00",
]

_file_cache = {}

def download_parquet(file_path):
    if file_path in _file_cache:
        return _file_cache[file_path]
    r = requests.get(f"{CHFD_BASE}/download", params={"file": file_path, "api_key": CHFD_KEY}, timeout=60)
    if not r.ok:
        return None
    data = zstd.decompress(r.content)
    df = pq.read_table(io.BytesIO(data), columns=["event_time", "side", "price", "quantity"]).to_pandas()
    df["price"] = df["price"].astype(float)
    df["quantity"] = df["quantity"].astype(float)
    _file_cache[file_path] = df
    return df


def get_book_debug(df, target_ms, label=""):
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        print(f"    {label}: NO DATA before target {target_ms}")
        return None, None, None

    actual_ts = subset["event_time"].max()
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]

    bids = book[book["side"] == "bid"].nlargest(1, "price")
    asks = book[book["side"] == "ask"].nsmallest(1, "price")

    best_bid = bids["price"].iloc[0] if not bids.empty else 0
    best_ask = asks["price"].iloc[0] if not asks.empty else 0

    return best_bid, best_ask, actual_ts


def get_file_path(dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{SYMBOL}_orderbook.parquet.zst"


def main():
    if not CHFD_KEY:
        print("ERROR: no key"); return

    print("=" * 90)
    print("DEBUG: T+10s vs T+1min exit timestamp verification")
    print("=" * 90)

    for time_str in DEBUG_SETTLEMENTS:
        dt = datetime.fromisoformat(time_str)
        ts_ms = int(dt.timestamp() * 1000)
        t_plus_10s = ts_ms + 10_000
        t_plus_1m = ts_ms + 60_000

        # Download needed files
        for d in [dt - timedelta(hours=1), dt, dt + timedelta(hours=1)]:
            download_parquet(get_file_path(d))

        # Combine
        dfs = []
        for d in [dt - timedelta(hours=1), dt, dt + timedelta(hours=1)]:
            p = get_file_path(d)
            if p in _file_cache:
                dfs.append(_file_cache[p])
        combined = pd.concat(dfs, ignore_index=True)

        # Show event_times near settlement
        near = combined[combined["event_time"].between(ts_ms, ts_ms + 120_000)]
        unique_times = sorted(near["event_time"].unique())

        print(f"\n{'=' * 90}")
        print(f"SETTLEMENT: {time_str}")
        print(f"  ts_ms = {ts_ms}")
        print(f"  T+10s target = {t_plus_10s}")
        print(f"  T+1min target = {t_plus_1m}")
        print(f"  Event times near settlement: {len(unique_times)} unique")
        if unique_times:
            print(f"  First 3: {unique_times[:3]}")
            print(f"  Last 3:  {unique_times[-3:]}")

        bb10, ba10, ts10 = get_book_debug(combined, t_plus_10s, "T+10s")
        bb1m, ba1m, ts1m = get_book_debug(combined, t_plus_1m, "T+1min")

        print(f"\n  T+10s exit:")
        if ts10:
            print(f"    Target:      {t_plus_10s}")
            print(f"    Actual used: {ts10}  (diff: {ts10 - t_plus_10s:+d}ms)")
            print(f"    Best bid:    {bb10:.6f}  Best ask: {ba10:.6f}")
        else:
            print(f"    NO DATA")

        print(f"\n  T+1min exit:")
        if ts1m:
            print(f"    Target:      {t_plus_1m}")
            print(f"    Actual used: {ts1m}  (diff: {ts1m - t_plus_1m:+d}ms)")
            print(f"    Best bid:    {bb1m:.6f}  Best ask: {ba1m:.6f}")
        else:
            print(f"    NO DATA")

        if ts10 and ts1m:
            same = ts10 == ts1m
            print(f"\n  Same snapshot? {'YES ← BUG!' if same else 'NO ✓'}")
            print(f"  Same bid?  {'YES' if bb10 == bb1m else 'NO'}  ({bb10:.6f} vs {bb1m:.6f})")
            print(f"  Same ask?  {'YES' if ba10 == ba1m else 'NO'}  ({ba10:.6f} vs {ba1m:.6f})")


if __name__ == "__main__":
    main()
