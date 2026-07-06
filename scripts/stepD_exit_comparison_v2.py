"""
LABUSDT exit comparison v2: fixed, with per-trade debug for first 3 settlements.
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
TOP_N = 20
ASTER_BASE = "https://fapi.asterdex.com"
TAKER_FEE_RT = 0.0008
SYMBOL = "LABUSDT"
LEVERAGE = 10
NOTIONAL = 500 * LEVERAGE


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


def get_book_at_time(df, target_ms, top_n=20):
    """Returns (book_dict, actual_timestamp_used)."""
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        return None, None
    actual_ts = int(subset["event_time"].max())
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]
    bids = book[book["side"] == "bid"].nlargest(top_n, "price").sort_values("price", ascending=False)
    asks = book[book["side"] == "ask"].nsmallest(top_n, "price").sort_values("price", ascending=True)
    return {
        "bids": list(zip(bids["price"].tolist(), bids["quantity"].tolist())),
        "asks": list(zip(asks["price"].tolist(), asks["quantity"].tolist())),
        "actual_ts": actual_ts,
    }, actual_ts


def walk_book(levels, notional_usd):
    remaining = notional_usd
    total_base = 0.0
    total_usd = 0.0
    for price, qty in levels:
        lv = price * qty
        if lv >= remaining:
            total_base += remaining / price
            total_usd += remaining
            remaining = 0
            break
        else:
            total_base += qty
            total_usd += lv
            remaining -= lv
    return total_usd, (total_usd / total_base if total_base > 0 else 0), total_base


def simulate(entry_book, exit_book, rate, notional):
    go_long = rate < 0
    if go_long:
        entry_levels = entry_book["asks"]
        exit_levels = exit_book["bids"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
    else:
        entry_levels = entry_book["bids"]
        exit_levels = exit_book["asks"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0

    e_filled, e_avg, e_base = walk_book(entry_levels, notional)
    if e_filled < notional * 0.20:
        return None

    x_filled, x_avg, x_base = walk_book(exit_levels, e_filled)
    e_slip = abs(e_avg - best_entry) / best_entry * 100 if best_entry else 0
    x_slip = abs(x_avg - best_exit) / best_exit * 100 if best_exit else 0

    if go_long:
        price_pnl = (x_avg - e_avg) * e_base
    else:
        price_pnl = (e_avg - x_avg) * e_base

    funding = e_filled * abs(rate)
    fees = e_filled * TAKER_FEE_RT
    slip = e_filled * e_slip / 100 + x_filled * x_slip / 100
    net = funding - fees - slip + price_pnl

    return {
        "entry_price": e_avg, "exit_price": x_avg,
        "entry_slip": e_slip, "exit_slip": x_slip,
        "funding": funding, "fees": fees, "slip": slip,
        "price_pnl": price_pnl, "net": net,
        "full": e_filled >= notional * 0.99,
    }


def get_file_path(dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{SYMBOL}_orderbook.parquet.zst"


def main():
    if not CHFD_KEY:
        print("ERROR: no key"); sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    entries = fetch_funding_history(SYMBOL)
    qualifying = [e for e in entries if e["fundingTime"] >= cutoff_ms and abs(float(e["fundingRate"])) >= THRESHOLD]
    print(f"  {len(qualifying)} qualifying settlements")

    # Download ALL needed files once
    files_needed = set()
    for e in qualifying:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        for offset in [-1, 0, 1, 2]:  # need +2h for T+1min exit in edge cases
            files_needed.add(get_file_path(dt + timedelta(hours=offset)))

    print(f"  Downloading {len(files_needed)} files...")
    for path in sorted(files_needed):
        download_parquet(path)
        time.sleep(0.1)
    print(f"  Downloaded {len([p for p in files_needed if p in _file_cache])}")

    # Run both variants
    variants = {"T+1min": 60_000, "T+10s": 10_000}
    results = {}

    for name, exit_offset_ms in variants.items():
        trades = []
        print(f"\n  Running {name}...")

        for idx, e in enumerate(qualifying):
            ts = e["fundingTime"]
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            rate = float(e["fundingRate"])

            # Entry: combine prev hour + settlement hour, target T-1min
            entry_dfs = []
            for h in [-1, 0]:
                p = get_file_path(dt + timedelta(hours=h))
                if p in _file_cache:
                    entry_dfs.append(_file_cache[p])
            if not entry_dfs:
                trades.append(None)
                continue
            entry_combined = pd.concat(entry_dfs, ignore_index=True)
            entry_book, _ = get_book_at_time(entry_combined, ts - 60_000)

            # Exit: combine hours around exit time, target T+offset
            exit_target_ms = ts + exit_offset_ms
            exit_dt = datetime.fromtimestamp(exit_target_ms / 1000, tz=timezone.utc)
            exit_dfs = []
            for h in [-1, 0, 1]:
                p = get_file_path(exit_dt + timedelta(hours=h))
                if p in _file_cache:
                    exit_dfs.append(_file_cache[p])
            if not exit_dfs:
                trades.append(None)
                continue
            exit_combined = pd.concat(exit_dfs, ignore_index=True)
            exit_book, actual_exit_ts = get_book_at_time(exit_combined, exit_target_ms)

            if not entry_book or not exit_book:
                trades.append(None)
                continue
            if not entry_book["bids"] or not entry_book["asks"]:
                trades.append(None)
                continue

            result = simulate(entry_book, exit_book, rate, NOTIONAL)
            if result:
                result["exit_actual_ts"] = actual_exit_ts
                result["exit_target_ms"] = exit_target_ms
            trades.append(result)

            # Debug first 3
            if idx < 3 and result:
                print(f"    [{idx}] {dt.isoformat()} rate={rate*100:.4f}%")
                print(f"        exit target={exit_target_ms} actual={actual_exit_ts} gap={actual_exit_ts-exit_target_ms:+d}ms")
                print(f"        exit best_bid={exit_book['bids'][0][0]:.6f} best_ask={exit_book['asks'][0][0]:.6f}")
                print(f"        exit_price={result['exit_price']:.6f} price_pnl={result['price_pnl']:+.4f} net={result['net']:+.4f}")

        filled = [t for t in trades if t is not None]
        results[name] = filled

    # Side-by-side
    print(f"\n{'=' * 80}")
    print(f"SIDE-BY-SIDE")
    print(f"{'=' * 80}")

    v1 = results["T+1min"]
    v2 = results["T+10s"]

    def stats(trades):
        nets = [t["net"] for t in trades]
        return {
            "count": len(trades),
            "total": sum(nets),
            "median": sorted(nets)[len(nets)//2],
            "worst": min(nets),
            "best": max(nets),
            "wins": sum(1 for x in nets if x > 0),
            "win_pct": sum(1 for x in nets if x > 0) / len(nets) * 100,
            "funding": sum(t["funding"] for t in trades),
            "price": sum(t["price_pnl"] for t in trades),
            "fees": sum(t["fees"] for t in trades),
            "slip": sum(t["slip"] for t in trades),
            "avg_exit_slip": sum(t["exit_slip"] for t in trades) / len(trades),
        }

    s1 = stats(v1)
    s2 = stats(v2)

    rows = [
        ("Trades", f"{s1['count']}", f"{s2['count']}"),
        ("Total net", f"€{s1['total']:+,.2f}", f"€{s2['total']:+,.2f}"),
        ("Median/trade", f"€{s1['median']:+,.2f}", f"€{s2['median']:+,.2f}"),
        ("Worst", f"€{s1['worst']:+,.2f}", f"€{s2['worst']:+,.2f}"),
        ("Best", f"€{s1['best']:+,.2f}", f"€{s2['best']:+,.2f}"),
        ("Win%", f"{s1['win_pct']:.1f}%", f"{s2['win_pct']:.1f}%"),
        ("", "", ""),
        ("Funding", f"€{s1['funding']:+,.2f}", f"€{s2['funding']:+,.2f}"),
        ("Price P&L", f"€{s1['price']:+,.2f}", f"€{s2['price']:+,.2f}"),
        ("Fees", f"€{s1['fees']:,.2f}", f"€{s2['fees']:,.2f}"),
        ("Slippage", f"€{s1['slip']:,.2f}", f"€{s2['slip']:,.2f}"),
        ("Avg exit slip", f"{s1['avg_exit_slip']:.4f}%", f"{s2['avg_exit_slip']:.4f}%"),
    ]

    print(f"\n  {'Metric':<20s} {'T+1min':>14s} {'T+10s':>14s} {'Delta':>10s}")
    print(f"  {'-' * 60}")
    for label, c1, c2 in rows:
        # Compute delta if numeric
        delta = ""
        try:
            v1_num = float(c1.replace("€", "").replace(",", "").replace("%", "").replace("+", ""))
            v2_num = float(c2.replace("€", "").replace(",", "").replace("%", "").replace("+", ""))
            d = v2_num - v1_num
            delta = f"€{d:+,.2f}" if "€" in c1 else f"{d:+.4f}%"
        except:
            pass
        print(f"  {label:<20s} {c1:>14s} {c2:>14s} {delta:>10s}")


if __name__ == "__main__":
    main()
