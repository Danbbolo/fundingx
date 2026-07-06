"""
LABUSDT backtest: T+1min exit vs T+10s exit comparison.
Same entry (T-1min market order), different exit windows.
Reports actual exit timestamp granularity from the L2 data.
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
BASE_SIZE = 500
NOTIONAL = BASE_SIZE * LEVERAGE


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
_MAX_CACHE = 12


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


def get_book_at_time(df, target_ms, top_n=20):
    subset = df[df["event_time"] <= target_ms]
    if subset.empty:
        return None, None
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]
    bids = book[book["side"] == "bid"].nlargest(top_n, "price").sort_values("price", ascending=False)
    asks = book[book["side"] == "ask"].nsmallest(top_n, "price").sort_values("price", ascending=True)
    # Get the actual last event_time used
    actual_ts = subset["event_time"].max()
    return {
        "bids": list(zip(bids["price"].tolist(), bids["quantity"].tolist())),
        "asks": list(zip(asks["price"].tolist(), asks["quantity"].tolist())),
    }, actual_ts


def walk_book(levels, notional_usd):
    remaining_usd = notional_usd
    total_base = 0.0
    total_usd = 0.0
    for price, qty_base in levels:
        level_usd = price * qty_base
        if level_usd >= remaining_usd:
            base_filled = remaining_usd / price
            total_base += base_filled
            total_usd += remaining_usd
            remaining_usd = 0
            break
        else:
            total_base += qty_base
            total_usd += level_usd
            remaining_usd -= level_usd
    avg_price = total_usd / total_base if total_base > 0 else 0
    return total_usd, avg_price, total_base


def simulate(entry_book, exit_book, settled_rate, notional_usd):
    go_long = settled_rate < 0
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

    entry_filled, entry_avg, entry_base = walk_book(entry_levels, notional_usd)
    if entry_filled < notional_usd * 0.20:
        return None

    exit_filled, exit_avg, exit_base = walk_book(exit_levels, entry_filled)
    entry_slip = abs(entry_avg - best_entry) / best_entry * 100 if best_entry > 0 else 0
    exit_slip = abs(exit_avg - best_exit) / best_exit * 100 if best_exit > 0 else 0

    if go_long:
        price_pnl = (exit_avg - entry_avg) * entry_base
    else:
        price_pnl = (entry_avg - exit_avg) * entry_base

    funding = entry_filled * abs(settled_rate)
    fees = entry_filled * TAKER_FEE_RT
    slip_cost = entry_filled * entry_slip / 100 + exit_filled * exit_slip / 100
    net = funding - fees - slip_cost + price_pnl

    return {
        "filled": round(entry_filled, 2),
        "entry_price": round(entry_avg, 6),
        "exit_price": round(exit_avg, 6),
        "entry_slip": round(entry_slip, 4),
        "exit_slip": round(exit_slip, 4),
        "funding": round(funding, 4),
        "fees": round(fees, 4),
        "slip_cost": round(slip_cost, 4),
        "price_pnl": round(price_pnl, 4),
        "net": round(net, 4),
        "full": entry_filled >= notional_usd * 0.99,
    }


def get_file_path(dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{SYMBOL}_orderbook.parquet.zst"


def get_combined(downloaded, dt):
    paths = [get_file_path(dt), get_file_path(dt - timedelta(hours=1))]
    dfs = [downloaded[p] for p in paths if p in downloaded]
    return pd.concat(dfs, ignore_index=True) if dfs else None


def main():
    print("=" * 80)
    print(f"LABUSDT: T+1min vs T+10s exit comparison")
    print(f"Notional: €{BASE_SIZE} × {LEVERAGE}x = €{NOTIONAL:,}")
    print("=" * 80)

    if not CHFD_KEY:
        print("ERROR: no key"); sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    entries = fetch_funding_history(SYMBOL)
    recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
    qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
    print(f"  {len(qualifying)} qualifying settlements")

    # Build file set: need T-1 and both T+1 variants
    files_needed = set()
    for e in qualifying:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        files_needed.add(get_file_path(dt - timedelta(hours=1)))
        files_needed.add(get_file_path(dt))
        files_needed.add(get_file_path(dt + timedelta(hours=1)))

    print(f"  Downloading {len(files_needed)} files...")
    downloaded = {}
    for path in sorted(files_needed):
        df = download_parquet(path)
        if df is not None and not df.empty:
            downloaded[path] = df
        time.sleep(0.15)
    print(f"  Downloaded {len(downloaded)}")

    # Check data granularity: find closest event_time to T+10s for first settlement
    first_e = qualifying[0]
    first_ts = first_e["fundingTime"]
    first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
    tp10s_ms = first_ts + 10_000

    first_entry_df = get_combined(downloaded, first_dt - timedelta(minutes=1))
    first_exit_df = get_combined(downloaded, first_dt + timedelta(minutes=1))

    if first_exit_df is not None:
        near_exit = first_exit_df[first_exit_df["event_time"].between(tp10s_ms - 5000, tp10s_ms + 5000)]
        if not near_exit.empty:
            closest_ts = near_exit["event_time"].iloc[0]
            diff_ms = closest_ts - tp10s_ms
            print(f"\n  GRANULARITY CHECK: target T+10s = {tp10s_ms}")
            print(f"  Closest data point: {closest_ts} (diff: {diff_ms:+d}ms)")
            # Check typical gap between updates near settlement
            times_near = first_exit_df[first_exit_df["event_time"].between(first_ts, first_ts + 60_000)]["event_time"].sort_values()
            if len(times_near) > 1:
                gaps = times_near.diff().dropna()
                print(f"  Update gaps near settlement: min={gaps.min():.0f}ms, median={gaps.median():.0f}ms, max={gaps.max():.0f}ms")
                print(f"  Data granularity: ~{gaps.median():.0f}ms between updates")
        else:
            print(f"\n  GRANULARITY CHECK: no data within ±5s of T+10s")

    # Run both exit variants
    variants = {
        "T+1min": lambda ts: ts + 60_000,
        "T+10s":  lambda ts: ts + 10_000,
    }

    results = {}
    for variant_name, exit_fn in variants.items():
        _file_cache.clear()
        trades = []
        exit_gaps = []  # actual vs target exit timestamps

        for e in qualifying:
            ts = e["fundingTime"]
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            rate = float(e["fundingRate"])

            entry_df = get_combined(downloaded, dt - timedelta(minutes=1))
            exit_target_ms = exit_fn(ts)
            exit_df = get_combined(downloaded, datetime.fromtimestamp(exit_target_ms / 1000, tz=timezone.utc))

            if entry_df is None or exit_df is None:
                trades.append(None)
                continue

            entry_book, _ = get_book_at_time(entry_df, ts - 60_000, top_n=TOP_N)
            exit_book, actual_exit_ts = get_book_at_time(exit_df, exit_target_ms, top_n=TOP_N)

            if actual_exit_ts:
                gap = actual_exit_ts - exit_target_ms
                exit_gaps.append(gap)

            if not entry_book or not exit_book or not entry_book["bids"] or not entry_book["asks"]:
                trades.append(None)
                continue

            result = simulate(entry_book, exit_book, rate, NOTIONAL)
            trades.append(result)

        filled = [t for t in trades if t is not None]
        results[variant_name] = {"trades": filled, "exit_gaps": exit_gaps}

    # ============================================================
    # SIDE-BY-SIDE OUTPUT
    # ============================================================

    # Exit gap stats for T+10s
    g = results["T+10s"]["exit_gaps"]
    if g:
        print(f"\n  T+10s exit gap stats (actual - target):")
        print(f"    Min: {min(g):+.0f}ms  Median: {sorted(g)[len(g)//2]:+.0f}ms  Max: {max(g):+.0f}ms")
        within_1s = sum(1 for x in g if abs(x) <= 1000)
        print(f"    Within ±1s: {within_1s}/{len(g)} ({within_1s/len(g)*100:.0f}%)")

    print(f"\n{'=' * 80}")
    print(f"SIDE-BY-SIDE COMPARISON")
    print(f"{'=' * 80}")

    header = f"  {'Metric':<28s} {'T+1min':>14s} {'T+10s':>14s} {'Delta':>10s}"
    print(f"\n{header}")
    print(f"  {'-' * 68}")

    for variant_name in ["T+1min", "T+10s"]:
        filled = results[variant_name]["trades"]
        r = results[variant_name]
        r["count"] = len(filled)
        r["nets"] = sorted([t["net"] for t in filled])
        r["total_net"] = sum(r["nets"])
        r["median"] = r["nets"][len(r["nets"]) // 2] if r["nets"] else 0
        r["worst"] = r["nets"][0] if r["nets"] else 0
        r["best"] = r["nets"][-1] if r["nets"] else 0
        r["wins"] = sum(1 for x in r["nets"] if x > 0)
        r["win_pct"] = r["wins"] / r["count"] * 100 if r["count"] else 0
        r["funding_total"] = sum(t["funding"] for t in filled)
        r["price_total"] = sum(t["price_pnl"] for t in filled)
        r["fees_total"] = sum(t["fees"] for t in filled)
        r["slip_total"] = sum(t["slip_cost"] for t in filled)
        r["avg_exit_slip"] = sum(t["exit_slip"] for t in filled) / len(filled) if filled else 0
        r["worst_exit_slip"] = max(t["exit_slip"] for t in filled) if filled else 0

    v1 = results["T+1min"]
    v2 = results["T+10s"]

    rows = [
        ("Trades", f"{v1['count']}", f"{v2['count']}", ""),
        ("Total net", f"€{v1['total_net']:+,.2f}", f"€{v2['total_net']:+,.2f}", f"€{v2['total_net'] - v1['total_net']:+,.2f}"),
        ("Median/trade", f"€{v1['median']:+,.2f}", f"€{v2['median']:+,.2f}", f"€{v2['median'] - v1['median']:+,.2f}"),
        ("Worst trade", f"€{v1['worst']:+,.2f}", f"€{v2['worst']:+,.2f}", f"€{v2['worst'] - v1['worst']:+,.2f}"),
        ("Best trade", f"€{v1['best']:+,.2f}", f"€{v2['best']:+,.2f}", f"€{v2['best'] - v1['best']:+,.2f}"),
        ("Win rate", f"{v1['win_pct']:.1f}%", f"{v2['win_pct']:.1f}%", f"{v2['win_pct'] - v1['win_pct']:+.1f}%"),
        ("", "", "", ""),
        ("Funding total", f"€{v1['funding_total']:+,.2f}", f"€{v2['funding_total']:+,.2f}", f"€{v2['funding_total'] - v1['funding_total']:+,.2f}"),
        ("Price P&L total", f"€{v1['price_total']:+,.2f}", f"€{v2['price_total']:+,.2f}", f"€{v2['price_total'] - v1['price_total']:+,.2f}"),
        ("Fees total", f"€{v1['fees_total']:,.2f}", f"€{v2['fees_total']:,.2f}", ""),
        ("Slippage total", f"€{v1['slip_total']:,.2f}", f"€{v2['slip_total']:,.2f}", f"€{v2['slip_total'] - v1['slip_total']:+,.2f}"),
        ("", "", "", ""),
        ("Avg exit slip", f"{v1['avg_exit_slip']:.4f}%", f"{v2['avg_exit_slip']:.4f}%", f"{v2['avg_exit_slip'] - v1['avg_exit_slip']:+.4f}%"),
        ("Worst exit slip", f"{v1['worst_exit_slip']:.4f}%", f"{v2['worst_exit_slip']:.4f}%", f"{v2['worst_exit_slip'] - v1['worst_exit_slip']:+.4f}%"),
    ]

    for label, col1, col2, delta in rows:
        print(f"  {label:<28s} {col1:>14s} {col2:>14s} {delta:>10s}")

    # Std comparison
    import statistics
    std1 = statistics.stdev(v1["nets"]) if len(v1["nets"]) > 1 else 0
    std2 = statistics.stdev(v2["nets"]) if len(v2["nets"]) > 1 else 0
    print(f"  {'Std dev':<28s} {'€%s' % f'{std1:,.2f}':>14s} {'€%s' % f'{std2:,.2f}':>14s} {'€%s' % f'{std2-std1:+,.2f}':>10s}")

    # Save
    with open("stepD_exit_comparison.json", "w") as f:
        json.dump({
            "T+1min": {"trades": v1["trades"], "total_net": v1["total_net"], "median": v1["median"], "worst": v1["worst"], "win_pct": v1["win_pct"]},
            "T+10s": {"trades": v2["trades"], "total_net": v2["total_net"], "median": v2["median"], "worst": v2["worst"], "win_pct": v2["win_pct"]},
        }, f, indent=2, default=str)
    print(f"\nSaved to stepD_exit_comparison.json")


if __name__ == "__main__":
    main()
