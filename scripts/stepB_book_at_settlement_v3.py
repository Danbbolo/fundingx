"""
Step B v3: Vectorized L2 replay — orders of magnitude faster than iterrows.
Key fix: use pandas groupby instead of iterating rows.
"""
import io
import json
import os
import sys
import time
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

_file_cache = {}
_MAX_CACHE = 10  # Keep only recent files to avoid OOM

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
    # Evict oldest entries if cache is full
    if len(_file_cache) >= _MAX_CACHE:
        oldest = list(_file_cache.keys())[:len(_file_cache) - _MAX_CACHE + 1]
        for k in oldest:
            del _file_cache[k]
    _file_cache[file_path] = df
    return df

def replay_book_vectorized(df, target_ms, top_n=5):
    """Vectorized L2 replay: filter, groupby last, sort. ~100x faster than iterrows."""
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        return None

    # Keep only the last quantity at each (side, price) — this is the book state
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]  # Remove zero-qty levels

    bids = book[book["side"] == "bid"].nlargest(top_n, "price")
    asks = book[book["side"] == "ask"].nsmallest(top_n, "price")

    bid_usdt = (bids["price"] * bids["quantity"]).sum()
    ask_usdt = (asks["price"] * asks["quantity"]).sum()
    return min(bid_usdt, ask_usdt)

def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"

def main():
    print("=" * 70)
    print("Step B v3: VECTORIZED L2 Book Reconstruction")
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
        print(f"  {len(qualifying)} qualifying, {len(recent)} total in last {LOOKBACK_DAYS}d")

        if not qualifying:
            continue

        # Build file set: settlement hour + previous hour
        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt))
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))

        print(f"  Files to download: {len(files_needed)}")

        # Download all
        downloaded = {}
        for i, path in enumerate(sorted(files_needed), 1):
            print(f"  [{i}/{len(files_needed)}] {path} ...", end="", flush=True)
            t0 = time.time()
            df = download_parquet(path)
            elapsed = time.time() - t0
            if df is not None and not df.empty:
                downloaded[path] = df
                print(f" OK ({len(df)} rows, {elapsed:.1f}s)")
            else:
                print(" EMPTY/MISSING")
            time.sleep(0.15)

        # Process each qualifying settlement
        coin_results = []
        zero_count = 0

        for e in qualifying:
            settlement_ts = e["fundingTime"]
            settled_rate = float(e["fundingRate"])
            settlement_dt = datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc)
            target_ms = settlement_ts - 5 * 60 * 1000  # T-5min

            # Get prev hour file (T-5min falls in previous hour)
            prev_dt = settlement_dt - timedelta(hours=1)
            prev_path = get_file_path(symbol, prev_dt)
            curr_path = get_file_path(symbol, settlement_dt)

            # Concatenate prev + current hour
            dfs = []
            if prev_path in downloaded:
                dfs.append(downloaded[prev_path])
            if curr_path in downloaded:
                dfs.append(downloaded[curr_path])

            if not dfs:
                coin_results.append({"settlement_time": settlement_dt.isoformat(), "settled_rate_pct": round(settled_rate * 100, 4), "book_5min_usdt": 0})
                zero_count += 1
                continue

            combined = pd.concat(dfs, ignore_index=True)
            book_val = replay_book_vectorized(combined, target_ms, top_n=TOP_N)

            if book_val and book_val > 0:
                coin_results.append({"settlement_time": settlement_dt.isoformat(), "settled_rate_pct": round(settled_rate * 100, 4), "book_5min_usdt": round(book_val, 2)})
            else:
                coin_results.append({"settlement_time": settlement_dt.isoformat(), "settled_rate_pct": round(settled_rate * 100, 4), "book_5min_usdt": 0})
                zero_count += 1

        # Calm baselines: use non-settlement files
        settlement_paths = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            settlement_paths.add(get_file_path(symbol, dt))

        for path, df in downloaded.items():
            if path in settlement_paths:
                continue
            mid_et = int(df["event_time"].median())
            val = replay_book_vectorized(df, mid_et, top_n=TOP_N)
            if val and val > 0:
                calm_baselines.setdefault(symbol, []).append(val)

        all_results[symbol] = coin_results
        nonzero = [r for r in coin_results if r["book_5min_usdt"] > 0]
        print(f"  Results: {len(nonzero)} with book, {zero_count} zero")

    # ============================================================
    # OUTPUT
    # ============================================================
    print(f"\n{'=' * 70}")
    print("VERDICT TABLE")
    print(f"{'=' * 70}")
    print(f"{'Symbol':<16s} {'Calm_Baseline':>14s} {'Worst_Case':>12s} {'Median':>12s} {'Best':>12s} {'Qual':>6s}")
    print("-" * 74)

    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        baselines = calm_baselines.get(symbol, [])
        if not results:
            print(f"{symbol:<16s} {'N/A':>14s} {'N/A':>12s} {'N/A':>12s} {'N/A':>12s} {'0':>6s}")
            continue

        books = [r["book_5min_usdt"] for r in results if r["book_5min_usdt"] > 0]
        calm_avg = round(sum(baselines) / len(baselines), 2) if baselines else 0
        worst = round(min(books), 2) if books else 0
        median = round(sorted(books)[len(books)//2], 2) if books else 0
        best = round(max(books), 2) if books else 0
        print(f"{symbol:<16s} {calm_avg:>14,.2f} {worst:>12,.2f} {median:>12,.2f} {best:>12,.2f} {len(results):>6d}")

    # Detail
    print(f"\n{'=' * 70}")
    print("PER-COIN DETAIL (worst 10)")
    print(f"{'=' * 70}")
    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        if not results:
            continue
        nonzero = [r for r in results if r["book_5min_usdt"] > 0]
        zero_ct = len(results) - len(nonzero)
        print(f"\n{symbol} ({len(results)} qualifying, {zero_ct} zero-book):")
        if nonzero:
            print(f"  {'Time':<28s} {'Rate%':>8s} {'Book_USDT':>12s}")
            print(f"  {'-'*50}")
            for r in sorted(nonzero, key=lambda x: x["book_5min_usdt"])[:10]:
                print(f"  {r['settlement_time']:<28s} {r['settled_rate_pct']:>8.4f} {r['book_5min_usdt']:>12,.2f}")

    with open("stepB_results_v3.json", "w") as f:
        json.dump({"results": all_results, "baselines": {k: round(sum(v)/len(v), 2) for k, v in calm_baselines.items()}}, f, indent=2, default=str)
    print(f"\nSaved to stepB_results_v3.json")

if __name__ == "__main__":
    main()
