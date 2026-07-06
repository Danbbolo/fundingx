"""
CORRECTED Backtest v2:
1. Direction fix: negative rate → LONG (longs receive), positive rate → SHORT (shorts receive)
2. Added price P&L: entry fill vs exit fill × position
3. Separate funding vs price P&L in summary

Source: https://docs.asterdex.com/trading/perpetuals/fees-and-specs/funding-rate.md
"Positive funding rate: long traders pay short traders."
"Negative funding rate: short traders pay long traders."
→ We go LONG when rate is negative (we receive), SHORT when rate is positive (we receive).
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

COINS = {
    "LABUSDT":   {"leverage": 10},
    "TAIKOUSDT": {"leverage": 5},
    "BIRBUSDT":  {"leverage": 5},
    "HUSDT":     {"leverage": 5},
}


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
        return None
    book = subset.groupby(["side", "price"])["quantity"].last().reset_index()
    book = book[book["quantity"] > 0]
    bids = book[book["side"] == "bid"].nlargest(top_n, "price").sort_values("price", ascending=False)
    asks = book[book["side"] == "ask"].nsmallest(top_n, "price").sort_values("price", ascending=True)
    return {
        "bids": list(zip(bids["price"].tolist(), bids["quantity"].tolist())),
        "asks": list(zip(asks["price"].tolist(), asks["quantity"].tolist())),
    }


def walk_book(levels, notional_usd):
    """Walk order book levels to fill a market order. Returns (filled_usd, avg_price, filled_base)."""
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


def simulate_settlement(entry_book, exit_book, settled_rate, notional_usd, verbose=False):
    """
    Corrected direction:
      Negative rate → LONG (longs RECEIVE): buy asks to enter, sell bids to exit
      Positive rate → SHORT (shorts RECEIVE): sell bids to enter, buy asks to exit
    """
    go_long = settled_rate < 0  # negative rate = longs receive

    if go_long:
        # LONG: buy asks to enter, sell bids to exit
        entry_levels = entry_book["asks"]
        exit_levels = exit_book["bids"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
        direction_label = "LONG"
    else:
        # SHORT: sell bids to enter, buy asks to exit
        entry_levels = entry_book["bids"]
        exit_levels = exit_book["asks"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
        direction_label = "SHORT"

    # Entry
    entry_filled_usd, entry_avg_price, entry_base = walk_book(entry_levels, notional_usd)
    if entry_filled_usd < notional_usd * 0.20:
        return None

    # Exit (close the position — consume the opposite side)
    exit_filled_usd, exit_avg_price, exit_base = walk_book(exit_levels, entry_filled_usd)

    # Slippage
    entry_slip_pct = abs(entry_avg_price - best_entry) / best_entry * 100 if best_entry > 0 else 0
    exit_slip_pct = abs(exit_avg_price - best_exit) / best_exit * 100 if best_exit > 0 else 0

    # Price P&L
    # LONG: profit = (exit_price - entry_price) / entry_price × notional
    # SHORT: profit = (entry_price - exit_price) / entry_price × notional
    if go_long:
        price_pnl = (exit_avg_price - entry_avg_price) * entry_base
    else:
        price_pnl = (entry_avg_price - exit_avg_price) * entry_base

    # Funding earned
    funding_earned = entry_filled_usd * abs(settled_rate)

    # Fees (round-trip taker)
    fees = entry_filled_usd * TAKER_FEE_RT

    # Slippage cost (both legs)
    slip_cost = entry_filled_usd * entry_slip_pct / 100 + exit_filled_usd * exit_slip_pct / 100

    # Net
    net_profit = funding_earned - fees - slip_cost + price_pnl

    is_full = entry_filled_usd >= notional_usd * 0.99

    result = {
        "direction": direction_label,
        "filled_usd": round(entry_filled_usd, 2),
        "entry_price": round(entry_avg_price, 6),
        "exit_price": round(exit_avg_price, 6),
        "entry_slip_pct": round(entry_slip_pct, 4),
        "exit_slip_pct": round(exit_slip_pct, 4),
        "funding_earned": round(funding_earned, 4),
        "fees": round(fees, 4),
        "slip_cost": round(slip_cost, 4),
        "price_pnl": round(price_pnl, 4),
        "net_profit": round(net_profit, 4),
        "is_full": is_full,
    }

    if verbose:
        print(f"    Direction: {direction_label} (rate={settled_rate*100:.4f}%)")
        print(f"    Entry: {entry_avg_price:.6f} × {entry_base:.4f} base = €{entry_filled_usd:,.2f} (slip {entry_slip_pct:.4f}%)")
        print(f"    Exit:  {exit_avg_price:.6f} × {exit_base:.4f} base = €{exit_filled_usd:,.2f} (slip {exit_slip_pct:.4f}%)")
        print(f"    Price P&L: €{price_pnl:+.4f} ({'exit' if go_long else 'entry'} - {'entry' if go_long else 'exit'} = {exit_avg_price:.6f} - {entry_avg_price:.6f})")
        print(f"    Funding:   €{funding_earned:.4f}")
        print(f"    Fees:      €{fees:.4f}")
        print(f"    Slip cost: €{slip_cost:.4f}")
        print(f"    NET:       €{net_profit:+.4f}")

    return result


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def get_combined(downloaded, symbol, dt):
    paths = [get_file_path(symbol, dt), get_file_path(symbol, dt - timedelta(hours=1))]
    dfs = [downloaded[p] for p in paths if p in downloaded]
    return pd.concat(dfs, ignore_index=True) if dfs else None


def main():
    print("=" * 80)
    print("CORRECTED BACKTEST v2: Funding direction + Price P&L")
    print("Direction: negative rate → LONG (receive), positive rate → SHORT (receive)")
    print("=" * 80)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    BASE_SIZES = [500, 250]
    grand_totals = {s: {"net": 0, "funding": 0, "price_pnl": 0, "fees": 0, "slip": 0, "trades": 0, "full": 0, "partial": 0, "skip": 0} for s in BASE_SIZES}

    for symbol, info in COINS.items():
        leverage = info["leverage"]
        print(f"\n{'=' * 80}")
        print(f"{symbol} — leverage {leverage}x")
        print(f"{'=' * 80}")

        entries = fetch_funding_history(symbol)
        if not entries:
            print("  No data")
            continue

        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"  {len(qualifying)} qualifying settlements in 14 days")

        if not qualifying:
            continue

        # Build file set
        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))
            files_needed.add(get_file_path(symbol, dt))
            files_needed.add(get_file_path(symbol, dt + timedelta(hours=1)))

        print(f"  Files to download: {len(files_needed)}")
        downloaded = {}
        for i, path in enumerate(sorted(files_needed), 1):
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
            time.sleep(0.15)
        print(f"  Downloaded {len(downloaded)} files")

        # --- Worked example ---
        first_e = qualifying[0]
        first_ts = first_e["fundingTime"]
        first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
        first_rate = float(first_e["fundingRate"])
        example_notional = 500 * leverage

        t1_dt = first_dt - timedelta(minutes=1)
        tp1_dt = first_dt + timedelta(minutes=1)
        entry_df = get_combined(downloaded, symbol, t1_dt)
        exit_df = get_combined(downloaded, symbol, tp1_dt)

        if entry_df is not None and exit_df is not None:
            entry_book = get_book_at_time(entry_df, first_ts - 60_000, top_n=TOP_N)
            exit_book = get_book_at_time(exit_df, first_ts + 60_000, top_n=TOP_N)

            if entry_book and exit_book:
                go_long = first_rate < 0
                walk_side = "ASKS (buy)" if go_long else "BIDS (sell)"
                levels = entry_book["asks"] if go_long else entry_book["bids"]

                print(f"\n{'=' * 80}")
                print(f"WORKED EXAMPLE: {symbol} {first_dt.isoformat()}")
                print(f"{'=' * 80}")
                print(f"  Settled rate: {first_rate} ({first_rate*100:.4f}%)")
                print(f"  Direction: {'LONG' if go_long else 'SHORT'} ({'longs' if go_long else 'shorts'} RECEIVE)")
                print(f"  Order: €500 × {leverage}x = €{example_notional:,.0f}")
                print(f"  Entry side: {walk_side}")
                print(f"\n  ENTRY BOOK — {walk_side} (top 10):")
                print(f"  {'#':>3s} {'Price':>12s} {'Qty_Base':>12s} {'Level_USD':>12s} {'Cum_USD':>12s}")
                cum = 0
                for j, (p, q) in enumerate(levels[:10]):
                    lv_usd = p * q
                    cum += lv_usd
                    marker = " <-- fills" if cum >= example_notional and cum - lv_usd < example_notional else ""
                    print(f"  {j+1:3d} {p:>12.6f} {q:>12.4f} {lv_usd:>12.2f} {cum:>12.2f}{marker}")

                result = simulate_settlement(entry_book, exit_book, first_rate, example_notional, verbose=True)

        # --- Bulk simulation ---
        for base_size in BASE_SIZES:
            notional = base_size * leverage
            coin_funding = 0
            coin_price_pnl = 0
            coin_fees = 0
            coin_slip = 0
            coin_net = 0
            full = partial = skip = 0
            trades = []

            for e in qualifying:
                ts = e["fundingTime"]
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                rate = float(e["fundingRate"])

                t1_dt = dt - timedelta(minutes=1)
                tp1_dt = dt + timedelta(minutes=1)
                entry_df = get_combined(downloaded, symbol, t1_dt)
                exit_df = get_combined(downloaded, symbol, tp1_dt)

                if entry_df is None or exit_df is None:
                    skip += 1
                    trades.append({"time": dt.isoformat(), "rate_pct": round(rate*100,4), "dir": "?", "filled": 0, "price_pnl": 0, "funding": 0, "net": 0, "status": "no_data"})
                    continue

                entry_book = get_book_at_time(entry_df, ts - 60_000, top_n=TOP_N)
                exit_book = get_book_at_time(exit_df, ts + 60_000, top_n=TOP_N)

                if not entry_book or not exit_book or not entry_book["bids"] or not entry_book["asks"]:
                    skip += 1
                    trades.append({"time": dt.isoformat(), "rate_pct": round(rate*100,4), "dir": "?", "filled": 0, "price_pnl": 0, "funding": 0, "net": 0, "status": "no_book"})
                    continue

                result = simulate_settlement(entry_book, exit_book, rate, notional)
                if result is None:
                    skip += 1
                    trades.append({"time": dt.isoformat(), "rate_pct": round(rate*100,4), "dir": "?", "filled": 0, "price_pnl": 0, "funding": 0, "net": 0, "status": "thin"})
                    continue

                if result["is_full"]:
                    full += 1
                else:
                    partial += 1

                coin_funding += result["funding_earned"]
                coin_price_pnl += result["price_pnl"]
                coin_fees += result["fees"]
                coin_slip += result["slip_cost"]
                coin_net += result["net_profit"]

                trades.append({
                    "time": dt.isoformat(),
                    "rate_pct": round(rate*100, 4),
                    "dir": result["direction"],
                    "filled": result["filled_usd"],
                    "price_pnl": result["price_pnl"],
                    "funding": result["funding_earned"],
                    "fees": result["fees"],
                    "slip": result["slip_cost"],
                    "net": result["net_profit"],
                    "status": "full" if result["is_full"] else "partial",
                })

            # Coin summary
            print(f"\n{'=' * 80}")
            print(f"{symbol} @ €{base_size} base × {leverage}x = €{notional:,.0f}")
            print(f"{'=' * 80}")
            print(f"  Full: {full}  Partial: {partial}  Skip: {skip}  Total: {len(trades)}")
            print(f"  Total funding:   €{coin_funding:+,.2f}")
            print(f"  Total price P&L: €{coin_price_pnl:+,.2f}")
            print(f"  Total fees:      €{coin_fees:,.2f}")
            print(f"  Total slippage:  €{coin_slip:,.2f}")
            print(f"  NET P&L:         €{coin_net:+,.2f}")
            print(f"  Per trade:       €{coin_net / max(len(trades), 1):+,.4f}")

            print(f"\n  {'Time':<28s} {'Dir':>5s} {'Rate%':>7s} {'Filled':>10s} {'PricePnL':>10s} {'Funding':>9s} {'Fees':>7s} {'Net':>10s} {'St':>4s}")
            print(f"  {'-'*95}")
            for t in trades:
                if t["filled"] > 0:
                    print(f"  {t['time']:<28s} {t['dir']:>5s} {t['rate_pct']:>7.3f} {t['filled']:>10,.2f} {t['price_pnl']:>+10.2f} {t['funding']:>9.4f} {t['fees']:>7.2f} {t['net']:>+10.2f} {t['status']:>4s}")

            gt = grand_totals[base_size]
            gt["net"] += coin_net
            gt["funding"] += coin_funding
            gt["price_pnl"] += coin_price_pnl
            gt["fees"] += coin_fees
            gt["slip"] += coin_slip
            gt["trades"] += len(trades)
            gt["full"] += full
            gt["partial"] += partial
            gt["skip"] += skip

    # Grand totals
    for base_size in BASE_SIZES:
        gt = grand_totals[base_size]
        print(f"\n{'=' * 80}")
        print(f"GRAND TOTAL — €{base_size} base")
        print(f"{'=' * 80}")
        print(f"  Coins traded: {sum(1 for s in COINS if gt['trades'] > 0)}")
        print(f"  Total trades: {gt['trades']} (full: {gt['full']}, partial: {gt['partial']}, skip: {gt['skip']})")
        print(f"  Total funding:   €{gt['funding']:+,.2f}")
        print(f"  Total price P&L: €{gt['price_pnl']:+,.2f}")
        print(f"  Total fees:      €{gt['fees']:,.2f}")
        print(f"  Total slippage:  €{gt['slip']:,.2f}")
        print(f"  NET P&L:         €{gt['net']:+,.2f}")
        print(f"  Per trade:       €{gt['net'] / max(gt['trades'], 1):+,.4f}")

    # Save
    with open("backtest_results_v2.json", "w") as f:
        json.dump({str(s): gt for s, gt in grand_totals.items()}, f, indent=2)
    print(f"\nSaved to backtest_results_v2.json")


if __name__ == "__main__":
    main()
