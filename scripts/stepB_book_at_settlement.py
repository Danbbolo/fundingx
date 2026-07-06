"""
Step B: Smart subset — download qualifying-settlement hours, replay L2, extract book at T-5min.
Also sample calm-hour baselines.
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

# ============================================================
# CONFIG
# ============================================================
CHFD_BASE = "https://api.cryptohftdata.com"
CHFD_KEY = os.environ.get("CRYPTOHFTDATA_API_KEY", "")
THRESHOLD = 0.0024
LOOKBACK_DAYS = 14
TOP_N = 5  # order book levels to sum

COINS = ["HOMEUSDT", "TAIKOUSDT", "COAIUSDT", "LABUSDT", "PIPPINUSDT", "HUSDT", "BEATUSDT", "BIRBUSDT", "AIAUSDT"]
COINS_HAVE_DATA = ["TAIKOUSDT", "LABUSDT", "HUSDT", "BIRBUSDT"]  # coins with qualifying events

ASTER_BASE = "https://fapi.asterdex.com"

# ============================================================
# HELPERS
# ============================================================

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


def download_parquet(file_path):
    """Download and decompress a parquet+zstd file. Returns pandas DataFrame."""
    r = requests.get(
        f"{CHFD_BASE}/download",
        params={"file": file_path, "api_key": CHFD_KEY},
        timeout=60,
    )
    if not r.ok:
        return None
    data = zstd.decompress(r.content)
    table = pq.read_table(io.BytesIO(data))
    return table.to_pandas()


def replay_book_at_time(df, target_ns, top_n=5):
    """
    Replay L2 updates up to target_ns (nanoseconds) and return top N levels.
    Returns dict with bids/asks as [(price, qty), ...] sorted correctly.
    """
    # Filter to updates before target
    subset = df[df["received_time"] <= target_ns].copy()
    if subset.empty:
        return None

    # Build book: last qty seen at each price level
    bids = {}  # price -> qty
    asks = {}

    for _, row in subset.iterrows():
        price = float(row["price"])
        qty = float(row["quantity"])
        side = row["side"]

        if side == "bid":
            if qty > 0:
                bids[price] = qty
            else:
                bids.pop(price, None)
        elif side == "ask":
            if qty > 0:
                asks[price] = qty
            else:
                asks.pop(price, None)

    # Sort: bids descending, asks ascending
    sorted_bids = sorted(bids.items(), key=lambda x: -x[0])[:top_n]
    sorted_asks = sorted(asks.items(), key=lambda x: x[0])[:top_n]

    return {"bids": sorted_bids, "asks": sorted_asks}


def book_usdt(book, top_n=5):
    """Sum top N levels in USDT, return smaller side."""
    bid_usdt = sum(p * q for p, q in book["bids"][:top_n])
    ask_usdt = sum(p * q for p, q in book["asks"][:top_n])
    return min(bid_usdt, ask_usdt)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("Step B: Smart Subset — L2 Book Reconstruction at Settlement T-5min")
    print("=" * 70)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set in environment")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    # Collect all results
    all_results = {}  # symbol -> list of {settlement_time, rate, book_usdt}
    calm_baselines = {}  # symbol -> avg book_usdt

    for symbol in COINS_HAVE_DATA:
        print(f"\n{'=' * 70}")
        print(f"Processing {symbol}")
        print(f"{'=' * 70}")

        # 1. Get funding history
        entries = fetch_funding_history(symbol)
        if not entries:
            print(f"  No funding data")
            continue

        # 2. Filter to last 14 days + qualifying
        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"  {len(qualifying)} qualifying settlements in last {LOOKBACK_DAYS} days")

        if not qualifying:
            continue

        # 3. Group by hour (which parquet file to download)
        hour_files = {}  # (date_str, hour_str) -> [entries]
        for e in qualifying:
            ts = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            key = (ts.strftime("%Y-%m-%d"), ts.strftime("%H"))
            hour_files.setdefault(key, []).append(e)

        print(f"  Unique hours to download: {len(hour_files)}")

        # 4. Download and process each hour
        coin_results = []
        downloaded = 0

        for (date_str, hour_str), entries_in_hour in sorted(hour_files.items()):
            path = f"aster_futures/{date_str}/{hour_str}/{symbol}_orderbook.parquet.zst"
            print(f"  [{downloaded+1}/{len(hour_files)}] {path} ...", end="", flush=True)

            try:
                df = download_parquet(path)
                if df is None or df.empty:
                    print(" EMPTY")
                    continue

                downloaded += 1

                # Process each settlement in this hour
                for e in entries_in_hour:
                    settlement_ts = e["fundingTime"]  # milliseconds
                    settled_rate = float(e["fundingRate"])
                    target_ns = (settlement_ts - 5 * 60 * 1000) * 1_000_000  # T-5min in nanoseconds

                    book = replay_book_at_time(df, target_ns, top_n=TOP_N)
                    if book:
                        book_val = book_usdt(book, top_n=TOP_N)
                        coin_results.append({
                            "settlement_time": datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc).isoformat(),
                            "settled_rate_pct": round(settled_rate * 100, 4),
                            "book_5min_usdt": round(book_val, 2),
                        })
                    else:
                        coin_results.append({
                            "settlement_time": datetime.fromtimestamp(settlement_ts / 1000, tz=timezone.utc).isoformat(),
                            "settled_rate_pct": round(settled_rate * 100, 4),
                            "book_5min_usdt": 0,
                        })

                # Calm baseline: use the midpoint of this hour as a "calm" snapshot
                mid_ns = df["received_time"].median()
                calm_book = replay_book_at_time(df, int(mid_ns), top_n=TOP_N)
                if calm_book:
                    calm_val = book_usdt(calm_book, top_n=TOP_N)
                    # Store as baseline (we'll average later)
                    calm_baselines.setdefault(symbol, []).append(calm_val)

                print(f" OK ({len(df)} rows)")

            except Exception as exc:
                print(f" ERROR: {exc}")
                continue

            time.sleep(0.3)

        all_results[symbol] = coin_results

    # ============================================================
    # OUTPUT
    # ============================================================
    print(f"\n{'=' * 70}")
    print("VERDICT TABLE")
    print(f"{'=' * 70}")
    print(f"{'Symbol':<16s} {'Calm_Baseline':>14s} {'Worst_Case':>12s} {'Max_Order':>12s} {'Qualifying':>10s} {'Sample':>6s}")
    print("-" * 72)

    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        baselines = calm_baselines.get(symbol, [])

        if not results:
            print(f"{symbol:<16s} {'N/A':>14s} {'N/A':>12s} {'N/A':>12s} {'0':>10s} {'0':>6s}")
            continue

        books = [r["book_5min_usdt"] for r in results]
        calm_avg = round(sum(baselines) / len(baselines), 2) if baselines else 0
        worst = round(min(books), 2)
        max_order = round(min(books), 2)  # worst-case book = max safe order size

        print(f"{symbol:<16s} {calm_avg:>14,.2f} {worst:>12,.2f} {max_order:>12,.2f} {len(results):>10d} {len(baselines):>6d}")

    # Per-coin detail
    print(f"\n{'=' * 70}")
    print("PER-COIN DETAIL")
    print(f"{'=' * 70}")
    for symbol in COINS_HAVE_DATA:
        results = all_results.get(symbol, [])
        if not results:
            continue
        print(f"\n{symbol} ({len(results)} qualifying settlements):")
        print(f"  {'Time':<28s} {'Rate%':>8s} {'Book_USDT':>12s}")
        print(f"  {'-'*50}")
        for r in sorted(results, key=lambda x: x["book_5min_usdt"])[:10]:
            print(f"  {r['settlement_time']:<28s} {r['settled_rate_pct']:>8.4f} {r['book_5min_usdt']:>12,.2f}")
        if len(results) > 10:
            print(f"  ... ({len(results)} total, showing worst 10)")

    # Save JSON
    output = {
        "results": all_results,
        "baselines": {k: round(sum(v)/len(v), 2) for k, v in calm_baselines.items()},
    }
    with open("stepB_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to stepB_results.json")


if __name__ == "__main__":
    main()
