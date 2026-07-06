"""
TASK 1: Fill missing coins in verdict table.
TASK 2: Entry timing analysis — book at T-30, T-15, T-5, T-1 for LABUSDT (+ PIPPIN if qualifying).
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
ASTER_BASE = "https://fapi.asterdex.com"

# Task 1 missing coins
TASK1_COINS = ["PIPPINUSDT", "COAIUSDT", "BEATUSDT", "AIAUSDT", "HOMEUSDT"]
# Task 2 timing coins (LABUSDT always, + PIPPIN if qualifying)
TASK2_COINS = ["LABUSDT"]  # will add PIPPIN if qualifying


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
        except Exception as e:
            print(f"    [ERR] {symbol}: {e}")
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
_MAX_CACHE = 10


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
    if len(_file_cache) >= _MAX_CACHE:
        oldest = list(_file_cache.keys())[:len(_file_cache) - _MAX_CACHE + 1]
        for k in oldest:
            del _file_cache[k]
    _file_cache[file_path] = df
    return df


def replay_book_at_time(df, target_ms, top_n=5):
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        return None
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]
    bids = book[book["side"] == "bid"].nlargest(top_n, "price")
    asks = book[book["side"] == "ask"].nsmallest(top_n, "price")
    bid_usdt = (bids["price"] * bids["quantity"]).sum()
    ask_usdt = (asks["price"] * asks["quantity"]).sum()
    return min(bid_usdt, ask_usdt)


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def check_chfd_symbol(symbol):
    """Check if cryptohftdata has orderbook data for a symbol."""
    r = requests.get(f"{CHFD_BASE}/symbols", params={"exchange": "aster_futures", "data_type": "orderbook"}, timeout=15)
    if not r.ok:
        return False
    symbols = r.json().get("symbols", [])
    return symbol in symbols


def run_settlement_analysis(symbol, qualifying):
    """Run T-5min settlement depth analysis for a symbol. Returns results list."""
    global _file_cache
    _file_cache.clear()  # Free memory

    # Build file set: settlement hour + previous hour
    files_needed = set()
    for e in qualifying:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        files_needed.add(get_file_path(symbol, dt))
        files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))

    print(f"    Files to download: {len(files_needed)}")

    # Download
    downloaded = {}
    for i, path in enumerate(sorted(files_needed), 1):
        print(f"    [{i}/{len(files_needed)}] {path.split('/')[-1]} ...", end="", flush=True)
        df = download_parquet(path)
        if df is not None and not df.empty:
            downloaded[path] = df
            print(f" OK ({len(df)})")
        else:
            print(" FAIL")
        time.sleep(0.15)

    # Process
    results = []
    for e in qualifying:
        settlement_ts = e["fundingTime"]
        settled_rate = float(e["fundingRate"])
        settlement_dt = datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc)
        target_ms = settlement_ts - 5 * 60 * 1000

        prev_path = get_file_path(symbol, settlement_dt - timedelta(hours=1))
        curr_path = get_file_path(symbol, settlement_dt)

        dfs = []
        if prev_path in downloaded:
            dfs.append(downloaded[prev_path])
        if curr_path in downloaded:
            dfs.append(downloaded[curr_path])

        if not dfs:
            results.append({"time": settlement_dt.isoformat(), "rate_pct": round(settled_rate * 100, 4), "book_usdt": 0})
            continue

        combined = pd.concat(dfs, ignore_index=True)
        val = replay_book_at_time(combined, target_ms, top_n=TOP_N)
        results.append({
            "time": settlement_dt.isoformat(),
            "rate_pct": round(settled_rate * 100, 4),
            "book_usdt": round(val, 2) if val and val > 0 else 0,
        })

    return results


def run_timing_analysis(symbol, qualifying):
    """Run 4-moment timing analysis: T-30, T-15, T-5, T-1 for each settlement."""
    global _file_cache
    _file_cache.clear()

    # We need hours covering T-30min to T-1min for each settlement
    # Worst case: T-30 falls 1 hour before settlement
    files_needed = set()
    for e in qualifying:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        files_needed.add(get_file_path(symbol, dt - timedelta(hours=2)))  # T-30 could fall 2h back
        files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))
        files_needed.add(get_file_path(symbol, dt))

    print(f"    Files to download: {len(files_needed)}")

    downloaded = {}
    for i, path in enumerate(sorted(files_needed), 1):
        print(f"    [{i}/{len(files_needed)}] {path.split('/')[-1]} ...", end="", flush=True)
        df = download_parquet(path)
        if df is not None and not df.empty:
            downloaded[path] = df
            print(f" OK ({len(df)})")
        else:
            print(" FAIL")
        time.sleep(0.15)

    LEAD_TIMES = [30, 15, 5, 1]  # minutes before settlement
    all_rows = []

    for e in qualifying:
        settlement_ts = e["fundingTime"]
        settled_rate = float(e["fundingRate"])
        settlement_dt = datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc)

        # Build combined df for all relevant hours
        relevant_hours = set()
        for mins in LEAD_TIMES:
            t_dt = datetime.fromtimestamp((settlement_ts - mins * 60 * 1000) / 1000, tz=timezone.utc)
            relevant_hours.add(get_file_path(symbol, t_dt))

        dfs = []
        for p in relevant_hours:
            if p in downloaded:
                dfs.append(downloaded[p])

        if not dfs:
            row = {"time": settlement_dt.isoformat(), "rate_pct": round(settled_rate * 100, 4)}
            for m in LEAD_TIMES:
                row[f"T-{m}"] = 0
            all_rows.append(row)
            continue

        combined = pd.concat(dfs, ignore_index=True)

        row = {"time": settlement_dt.isoformat(), "rate_pct": round(settled_rate * 100, 4)}
        for mins in LEAD_TIMES:
            target_ms = settlement_ts - mins * 60 * 1000
            val = replay_book_at_time(combined, target_ms, top_n=TOP_N)
            row[f"T-{mins}"] = round(val, 2) if val and val > 0 else 0

        all_rows.append(row)

    return all_rows


def main():
    print("=" * 70)
    print("TASK 1: Missing Coins + TASK 2: Entry Timing")
    print("=" * 70)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    # ============================================================
    # TASK 1: Missing coins
    # ============================================================
    print(f"\n{'=' * 70}")
    print("TASK 1: Missing Coins")
    print(f"{'=' * 70}")

    task1_results = {}

    for symbol in TASK1_COINS:
        print(f"\n--- {symbol} ---")

        # Check if cryptohftdata has the symbol
        has_data = check_chfd_symbol(symbol)
        if not has_data:
            print(f"    STATUS: NO DATA at cryptohftdata")
            task1_results[symbol] = {"status": "no_data_at_chfd"}
            continue

        # Get qualifying events
        entries = fetch_funding_history(symbol)
        if not entries:
            print(f"    STATUS: NO FUNDING DATA from Aster")
            task1_results[symbol] = {"status": "no_funding_data"}
            continue

        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"    {len(qualifying)} qualifying in last {LOOKBACK_DAYS}d ({len(recent)} total)")

        if not qualifying:
            print(f"    STATUS: 0 QUALIFYING in last 14 days")
            task1_results[symbol] = {"status": "no_qualifying_14d", "total_recent": len(recent)}
            continue

        # Run settlement analysis
        results = run_settlement_analysis(symbol, qualifying)
        books = [r["book_usdt"] for r in results if r["book_usdt"] > 0]

        if books:
            calm_val = round(sum(books) / len(books), 2)  # use median as rough calm
            task1_results[symbol] = {
                "status": "analyzed",
                "qualifying": len(qualifying),
                "calm_baseline": calm_val,
                "worst": round(min(books), 2),
                "median": round(sorted(books)[len(books)//2], 2),
                "best": round(max(books), 2),
                "detail": sorted([r for r in results if r["book_usdt"] > 0], key=lambda x: x["book_usdt"])[:5],
            }
            # If PIPPIN qualifies, add to Task 2
            if symbol == "PIPPINUSDT" and len(qualifying) >= 10:
                TASK2_COINS.append("PIPPINUSDT")
                print(f"    PIPPIN qualifies! Adding to Task 2 timing analysis.")

            print(f"    STATUS: ANALYZED — worst=${min(books):,.0f} median=${sorted(books)[len(books)//2]:,.0f} best=${max(books):,.0f}")
        else:
            task1_results[symbol] = {"status": "all_zero_book", "qualifying": len(qualifying)}

    # ============================================================
    # TASK 2: Entry timing
    # ============================================================
    print(f"\n{'=' * 70}")
    print("TASK 2: Entry Timing Analysis (T-30, T-15, T-5, T-1)")
    print(f"{'=' * 70}")

    task2_results = {}

    for symbol in TASK2_COINS:
        print(f"\n--- {symbol} timing ---")

        entries = fetch_funding_history(symbol)
        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]

        if not qualifying:
            print(f"    No qualifying events")
            continue

        print(f"    {len(qualifying)} qualifying settlements")

        timing_rows = run_timing_analysis(symbol, qualifying)
        task2_results[symbol] = timing_rows

    # ============================================================
    # OUTPUT
    # ============================================================
    print(f"\n{'=' * 70}")
    print("TASK 1: UPDATED VERDICT TABLE")
    print(f"{'=' * 70}")
    print(f"{'Symbol':<16s} {'Status':<22s} {'Baseline':>10s} {'Worst':>10s} {'Median':>10s} {'Best':>10s} {'Qual':>5s}")
    print("-" * 85)

    for symbol in TASK1_COINS:
        r = task1_results[symbol]
        if r["status"] == "analyzed":
            print(f"{symbol:<16s} {'OK':<22s} {r['calm_baseline']:>10,.0f} {r['worst']:>10,.0f} {r['median']:>10,.0f} {r['best']:>10,.0f} {r['qualifying']:>5d}")
        elif r["status"] == "no_qualifying_14d":
            print(f"{symbol:<16s} {'0 qualifying (14d)':<22s} {'—':>10s} {'—':>10s} {'—':>10s} {'—':>10s} {'0':>5s}")
        elif r["status"] == "no_data_at_chfd":
            print(f"{symbol:<16s} {'No data at CHFD':<22s} {'—':>10s} {'—':>10s} {'—':>10s} {'—':>10s} {'—':>5s}")
        else:
            print(f"{symbol:<16s} {r['status']:<22s} {'—':>10s} {'—':>10s} {'—':>10s} {'—':>10s} {'—':>5s}")

    # Task 1 detail for analyzed coins
    for symbol in TASK1_COINS:
        r = task1_results.get(symbol, {})
        if r.get("detail"):
            print(f"\n{symbol} — worst 5 settlements:")
            print(f"  {'Time':<28s} {'Rate%':>8s} {'Book_USDT':>10s}")
            print(f"  {'-'*48}")
            for d in r["detail"]:
                print(f"  {d['time']:<28s} {d['rate_pct']:>8.4f} {d['book_usdt']:>10,.2f}")

    # Task 2 timing output
    print(f"\n{'=' * 70}")
    print("TASK 2: ENTRY TIMING — Median & Worst at Each Lead Time")
    print(f"{'=' * 70}")

    for symbol, rows in task2_results.items():
        print(f"\n--- {symbol} ({len(rows)} settlements) ---")
        print(f"  {'Lead Time':>10s} {'Median':>12s} {'Worst':>12s} {'Best':>12s}")
        print(f"  {'-'*48}")
        for mins in [30, 15, 5, 1]:
            col = f"T-{mins}"
            vals = [r[col] for r in rows if r[col] > 0]
            if vals:
                med = sorted(vals)[len(vals)//2]
                print(f"  T-{mins:>2d}min    {med:>12,.2f} {min(vals):>12,.2f} {max(vals):>12,.2f}")
            else:
                print(f"  T-{mins:>2d}min    {'N/A':>12s} {'N/A':>12s} {'N/A':>12s}")

        # 5 thinnest events with all 4 moments
        thinnest = sorted(rows, key=lambda r: r.get("T-5", 0))[:5]
        print(f"\n  5 thinnest T-5min events:")
        print(f"  {'Time':<28s} {'Rate%':>7s} {'T-30':>10s} {'T-15':>10s} {'T-5':>10s} {'T-1':>10s}")
        print(f"  {'-'*78}")
        for r in thinnest:
            print(f"  {r['time']:<28s} {r['rate_pct']:>7.3f} {r.get('T-30',0):>10,.2f} {r.get('T-15',0):>10,.2f} {r.get('T-5',0):>10,.2f} {r.get('T-1',0):>10,.2f}")

    # Save
    output = {
        "task1_missing_coins": task1_results,
        "task2_timing": {k: v for k, v in task2_results.items()},
    }
    with open("stepBC_timing_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to stepBC_timing_results.json")


if __name__ == "__main__":
    main()
