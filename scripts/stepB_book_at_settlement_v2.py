"""
Step B v2: Smart subset with previous-hour download fix.
For each qualifying settlement, download BOTH the settlement hour AND the previous hour,
concatenate, then replay to T-5min.
"""
import io
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import pandas as pd
import pyarrow.parquet as pq
import requests
import zstandard as zstd

CHFD_BASE = "https://api.cryptohftdata.com"
CHFD_KEY = os.environ.get("CRYPTOHFTDATA_API_KEY", "")
THRESHOLD = 0.0024
LOOKBACK_DAYS = 14
TOP_N = 5

COINS_HAVE_DATA = ["TAIKOUSDT", "LABUSDT", "HUSDT", "BIRBUSDT"]
ASTER_BASE = "https://fapi.asterdex.com"

def fetch_funding_history(symbol):
    all_entries = []
    end_time = None
    while True:
        params = {"symbol": symbol, "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        try:
            r = requests.get(f"{ASTER_BASE}/fapi/v1/fundingRate", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except:
            break
        if not data:
            break
        all_entries.extend(data)
        if len(data) < 1000:
            break
        end_time = data[0]["fundingTime"] - 1
        time.sleep(0.1)
    return all_entries

# Cache for downloaded parquet files
_file_cache = {}

def download_parquet(file_path):
    if file_path in _file_cache:
        return _file_cache[file_path]
    r = requests.get(f"{CHFD_BASE}/download", params={"file": file_path, "api_key": CHFD_KEY}, timeout=60)
    if not r.ok:
        return None
    data = zstd.decompress(r.content)
    df = pq.read_table(io.BytesIO(data)).to_pandas()
    _file_cache[file_path] = df
    return df


def replay_book_at_time(df, target_ms, top_n=5):
    """Replay L2 updates up to target_ms (milliseconds) using event_time."""
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        return None

    bids = {}
    asks = {}
    for _, row in subset.iterrows():
        price = float(row["price"])
        qty = float(row["quantity"])
        if row["side"] == "bid":
            if qty > 0:
                bids[price] = qty
            else:
                bids.pop(price, None)
        else:
            if qty > 0:
                asks[price] = qty
            else:
                asks.pop(price, None)

    sorted_bids = sorted(bids.items(), key=lambda x: -x[0])[:top_n]
    sorted_asks = sorted(asks.items(), key=lambda x: x[0])[:top_n]
    return {"bids": sorted_bids, "asks": sorted_asks}


def book_usdt(book, top_n=5):
    bid_usdt = sum(p * q for p, q in book["bids"][:top_n])
    ask_usdt = sum(p * q for p, q in book["asks"][:top_n])
    return min(bid_usdt, ask_usdt)


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def main():
    print("=" * 70)
    print("Step B v2: L2 Book Reconstruction (with prev-hour fix)")
    print("=" * 70)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    all_results = {}
    calm_baselines = {}

    for symbol in COINS_HAVE_DATA:
        print(f"\n{'=' * 70}")
        print(f"Processing {symbol}")
        print(f"{'=' * 70}")

        entries = fetch_funding_history(symbol)
        if not entries:
            continue

        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"  {len(qualifying)} qualifying settlements in last {LOOKBACK_DAYS} days")

        if not qualifying:
            continue

        # Group by hour — we need BOTH the settlement hour AND the previous hour
        files_needed = set()
        hour_entries = {}  # file_path -> [entries]

        for e in qualifying:
            settlement_ts = e["fundingTime"]
            settlement_dt = datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc)

            # Current hour file
            current_path = get_file_path(symbol, settlement_dt)
            files_needed.add(current_path)
            hour_entries.setdefault(current_path, []).append(e)

            # Previous hour file (for T-5min data)
            prev_dt = settlement_dt - timedelta(hours=1)
            prev_path = get_file_path(symbol, prev_dt)
            files_needed.add(prev_path)

        print(f"  Files to download: {len(files_needed)} (settlement hours + previous hours)")

        # Download all files
        downloaded = {}
        for i, path in enumerate(sorted(files_needed), 1):
            print(f"  [{i}/{len(files_needed)}] {path} ...", end="", flush=True)
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
                print(f" OK ({len(df)} rows)")
            else:
                print(" EMPTY/MISSING")
            time.sleep(0.2)

        # Process each qualifying settlement
        coin_results = []
        for e in qualifying:
            settlement_ts = e["fundingTime"]
            settled_rate = float(e["fundingRate"])
            settlement_dt = datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc)

            # T-5min target in milliseconds
            target_ms = settlement_ts - 5 * 60 * 1000

            # Get the correct file (previous hour for T-5min)
            target_dt = datetime.fromtimestamp(target_ms / 1000, tz=timezone.utc)
            target_path = get_file_path(symbol, target_dt)

            # If T-5min is in the same hour as settlement, we need the previous hour
            if target_dt.hour != settlement_dt.hour:
                target_path = get_file_path(symbol, target_dt)

            df = downloaded.get(target_path)
            if df is None:
                # Try concatenating current and previous hour
                current_path = get_file_path(symbol, settlement_dt)
                prev_path = get_file_path(symbol, settlement_dt - timedelta(hours=1))
                dfs = []
                if prev_path in downloaded:
                    dfs.append(downloaded[prev_path])
                if current_path in downloaded:
                    dfs.append(downloaded[current_path])
                if dfs:
                    df = pd.concat(dfs, ignore_index=True)

            if df is None:
                coin_results.append({
                    "settlement_time": settlement_dt.isoformat(),
                    "settled_rate_pct": round(settled_rate * 100, 4),
                    "book_5min_usdt": 0,
                })
                continue

            book = replay_book_at_time(df, target_ms, top_n=TOP_N)
            if book:
                book_val = book_usdt(book, top_n=TOP_N)
                coin_results.append({
                    "settlement_time": settlement_dt.isoformat(),
                    "settled_rate_pct": round(settled_rate * 100, 4),
                    "book_5min_usdt": round(book_val, 2),
                })
            else:
                coin_results.append({
                    "settlement_time": settlement_dt.isoformat(),
                    "settled_rate_pct": round(settled_rate * 100, 4),
                    "book_5min_usdt": 0,
                })

        # Calm baseline: use midpoint of each downloaded file
        for path, df in downloaded.items():
            if path in hour_entries:
                continue  # Skip settlement hours for calm baseline
            mid_et = df["event_time"].median()
            calm_book = replay_book_at_time(df, int(mid_et), top_n=TOP_N)
            if calm_book:
                calm_val = book_usdt(calm_book, top_n=TOP_N)
                calm_baselines.setdefault(symbol, []).append(calm_val)

        all_results[symbol] = coin_results

    # ============================================================
    # OUTPUT
    # ============================================================
    print(f"\n{'=' * 70}")
    print("VERDICT TABLE")
    print(f"{'=' * 70}")
    print(f"{'Symbol':<16s} {'Calm_Baseline':>14s} {'Worst_Case':>12s} {'Median':>12s} {'Qualifying':>10s}")
    print("-" * 66)

    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        baselines = calm_baselines.get(symbol, [])
        if not results:
            print(f"{symbol:<16s} {'N/A':>14s} {'N/A':>12s} {'N/A':>12s} {'0':>10s}")
            continue

        books = [r["book_5min_usdt"] for r in results if r["book_5min_usdt"] > 0]
        calm_avg = round(sum(baselines) / len(baselines), 2) if baselines else 0
        worst = round(min(books), 2) if books else 0
        median = round(sorted(books)[len(books)//2], 2) if books else 0
        print(f"{symbol:<16s} {calm_avg:>14,.2f} {worst:>12,.2f} {median:>12,.2f} {len(results):>10d}")

    # Per-coin detail (worst 10)
    print(f"\n{'=' * 70}")
    print("PER-COIN DETAIL (worst 10 settlements)")
    print(f"{'=' * 70}")
    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        if not results:
            continue
        nonzero = [r for r in results if r["book_5min_usdt"] > 0]
        zero_count = len(results) - len(nonzero)
        print(f"\n{symbol} ({len(results)} qualifying, {zero_count} zero-book):")
        print(f"  {'Time':<28s} {'Rate%':>8s} {'Book_USDT':>12s}")
        print(f"  {'-'*50}")
        for r in sorted(nonzero, key=lambda x: x["book_5min_usdt"])[:10]:
            print(f"  {r['settlement_time']:<28s} {r['settled_rate_pct']:>8.4f} {r['book_5min_usdt']:>12,.2f}")

    output = {"results": all_results, "baselines": {k: round(sum(v)/len(v), 2) for k, v in calm_baselines.items()}}
    with open("stepB_results_v2.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to stepB_results_v2.json")


if __name__ == "__main__":
    main()
