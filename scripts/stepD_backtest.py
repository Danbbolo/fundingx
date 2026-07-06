"""
Backtest simulation: €500 sniper on LABUSDT, TAIKOUSDT, BIRBUSDT, HUSDT.
Walks historical order books at T-1min entry / T+1min exit.
Computes: filled notional, slippage both legs, funding earned, fees, net profit.
Runs at €500 base and €250 base.
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
TOP_N = 20  # levels to walk
ASTER_BASE = "https://fapi.asterdex.com"
TAKER_FEE_RT = 0.0008  # round-trip taker fee

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
    """Get top N levels each side as lists of (price, qty_in_base)."""
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


def walk_book(levels, notional_usd, side="buy"):
    """
    Walk order book levels to fill a market order.
    side='buy': consume asks (we're buying base)
    side='sell': consume bids (we're selling base)
    Returns: (filled_notional_usd, avg_fill_price, filled_base, levels_consumed)
    """
    remaining_usd = notional_usd
    total_base = 0.0
    total_usd_spent = 0.0
    levels_used = 0

    for price, qty_base in levels:
        level_usd = price * qty_base
        if level_usd >= remaining_usd:
            # This level can fill the rest
            base_filled = remaining_usd / price
            total_base += base_filled
            total_usd_spent += remaining_usd
            levels_used += 1
            remaining_usd = 0
            break
        else:
            # Consume entire level
            total_base += qty_base
            total_usd_spent += level_usd
            remaining_usd -= level_usd
            levels_used += 1

    filled_notional = total_usd_spent
    avg_fill_price = total_usd_spent / total_base if total_base > 0 else 0
    return filled_notional, avg_fill_price, total_base, levels_used


def simulate_settlement(book_entry, book_exit, settled_rate, notional_usd, verbose=False):
    """
    Simulate one settlement trade.
    Negative rate → SHORT: sell (bids) to enter, buy (asks) to exit.
    Positive rate → LONG: buy (asks) to enter, sell (bids) to exit.
    """
    is_short = settled_rate < 0

    if is_short:
        # Entry: SELL consuming bids
        entry_levels = book_entry["bids"]
        # Exit: BUY consuming asks
        exit_levels = book_exit["asks"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
    else:
        # Entry: BUY consuming asks
        entry_levels = book_entry["asks"]
        # Exit: SELL consuming bids
        exit_levels = book_exit["bids"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0

    # Walk entry book
    entry_filled, entry_avg, entry_base, entry_levels_used = walk_book(entry_levels, notional_usd, "buy" if not is_short else "sell")

    if entry_filled < notional_usd * 0.20:
        return None  # Skip — less than 20% filled

    # Walk exit book (same notional that was filled)
    exit_filled, exit_avg, exit_base, exit_levels_used = walk_book(exit_levels, entry_filled, "sell" if not is_short else "buy")

    # Slippage
    if best_entry > 0:
        entry_slip_pct = abs(entry_avg - best_entry) / best_entry * 100
    else:
        entry_slip_pct = 0
    if best_exit > 0:
        exit_slip_pct = abs(exit_avg - best_exit) / best_exit * 100
    else:
        exit_slip_pct = 0

    # Costs
    funding_earned = entry_filled * abs(settled_rate)
    fees = entry_filled * TAKER_FEE_RT
    slip_cost_entry = entry_filled * entry_slip_pct / 100
    slip_cost_exit = exit_filled * exit_slip_pct / 100
    slip_cost = slip_cost_entry + slip_cost_exit

    net_profit = funding_earned - fees - slip_cost

    is_full = entry_filled >= notional_usd * 0.99
    is_partial = not is_full and entry_filled >= notional_usd * 0.20

    return {
        "filled_notional": round(entry_filled, 2),
        "entry_slip_pct": round(entry_slip_pct, 4),
        "exit_slip_pct": round(exit_slip_pct, 4),
        "funding_earned": round(funding_earned, 4),
        "fees": round(fees, 4),
        "slip_cost": round(slip_cost, 4),
        "net_profit": round(net_profit, 4),
        "is_full": is_full,
        "is_partial": is_partial,
        "entry_levels_used": entry_levels_used,
        "exit_levels_used": exit_levels_used,
    }


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def main():
    print("=" * 80)
    print("BACKTEST: €500 Funding Sniper Simulation")
    print("=" * 80)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    BASE_SIZES = [500, 250]
    grand_totals = {s: {"net": 0, "trades": 0, "coins": 0} for s in BASE_SIZES}

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

        # Build file set: need T-1 and T+1 for each settlement
        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))  # T-1min falls in prev hour
            files_needed.add(get_file_path(symbol, dt))                        # settlement hour
            files_needed.add(get_file_path(symbol, dt + timedelta(hours=1)))  # T+1min falls in next hour

        print(f"  Files to download: {len(files_needed)}")
        downloaded = {}
        for i, path in enumerate(sorted(files_needed), 1):
            print(f"  [{i}/{len(files_needed)}] {path.split('/')[-1]} ...", end="", flush=True)
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
                print(f" OK ({len(df)})")
            else:
                print(" FAIL")
            time.sleep(0.15)

        # --- Print one worked example ---
        first_e = qualifying[0]
        first_ts = first_e["fundingTime"]
        first_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
        first_rate = float(first_e["fundingRate"])
        example_notional = 500 * leverage

        # Get entry book (T-1min) and exit book (T+1min)
        t1_ms = first_ts - 1 * 60 * 1000
        t1_dt = datetime.fromtimestamp(t1_ms / 1000, tz=timezone.utc)
        t1_path = get_file_path(symbol, t1_dt)

        tp1_ms = first_ts + 1 * 60 * 1000
        tp1_dt = datetime.fromtimestamp(tp1_ms / 1000, tz=timezone.utc)
        tp1_path = get_file_path(symbol, tp1_dt)

        # Combine hours for each
        def get_combined(dt):
            paths = [get_file_path(symbol, dt), get_file_path(symbol, dt - timedelta(hours=1))]
            dfs = [downloaded[p] for p in paths if p in downloaded]
            return pd.concat(dfs, ignore_index=True) if dfs else None

        entry_df = get_combined(t1_dt)
        exit_df = get_combined(tp1_dt)

        if entry_df is not None and exit_df is not None:
            entry_book = get_book_at_time(entry_df, t1_ms, top_n=TOP_N)
            exit_book = get_book_at_time(exit_df, tp1_ms, top_n=TOP_N)

            if entry_book and exit_book:
                is_short = first_rate < 0
                if is_short:
                    walk_levels = entry_book["bids"]
                    exit_levels = entry_book["asks"]
                    direction_label = "SHORT (sell bids to enter, buy asks to exit)"
                else:
                    walk_levels = entry_book["asks"]
                    exit_levels = entry_book["bids"]
                    direction_label = "LONG (buy asks to enter, sell bids to exit)"

                print(f"\n{'=' * 80}")
                print(f"WORKED EXAMPLE: {symbol} {first_dt.isoformat()}")
                print(f"{'=' * 80}")
                print(f"  Settled rate: {first_rate} ({first_rate*100:.4f}%)")
                print(f"  Direction: {direction_label}")
                print(f"  Order size: €{500} × {leverage}x = €{example_notional:,.0f}")
                print(f"\n  ENTRY BOOK (T-1min) — {'BIDS' if is_short else 'ASKS'} side (top {min(10, TOP_N)}):")
                print(f"  {'#':>3s} {'Price':>12s} {'Qty_Base':>12s} {'Level_USD':>12s} {'Cum_USD':>12s}")
                cum = 0
                for j, (p, q) in enumerate(walk_levels[:10]):
                    lv_usd = p * q
                    cum += lv_usd
                    fill_indicator = " <-- fills here" if cum >= example_notional and cum - lv_usd < example_notional else ""
                    print(f"  {j+1:3d} {p:>12.4f} {q:>12.4f} {lv_usd:>12.2f} {cum:>12.2f}{fill_indicator}")

                result = simulate_settlement(entry_book, exit_book, first_rate, example_notional)
                if result:
                    print(f"\n  RESULT:")
                    print(f"    Filled: €{result['filled_notional']:,.2f} / €{example_notional:,.0f}")
                    print(f"    Entry slip: {result['entry_slip_pct']:.4f}%")
                    print(f"    Exit slip:  {result['exit_slip_pct']:.4f}%")
                    print(f"    Funding:    €{result['funding_earned']:.4f}")
                    print(f"    Fees:       €{result['fees']:.4f}")
                    print(f"    Slip cost:  €{result['slip_cost']:.4f}")
                    print(f"    NET:        €{result['net_profit']:.4f}")

        # --- Bulk simulation ---
        for base_size in BASE_SIZES:
            notional = base_size * leverage
            coin_results = []
            full_fills = partial_fills = skips = 0
            coin_net = 0.0

            for e in qualifying:
                ts = e["fundingTime"]
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                rate = float(e["fundingRate"])

                # Entry book at T-1min
                t1_dt = dt - timedelta(minutes=1)
                entry_df = get_combined(t1_dt)
                # Exit book at T+1min
                tp1_dt = dt + timedelta(minutes=1)
                exit_df = get_combined(tp1_dt)

                if entry_df is None or exit_df is None:
                    skips += 1
                    coin_results.append({"time": dt.isoformat(), "rate_pct": round(rate*100, 4), "filled": 0, "slip": 0, "net": 0, "status": "no_data"})
                    continue

                t1_ms = ts - 60_000
                tp1_ms = ts + 60_000
                entry_book = get_book_at_time(entry_df, t1_ms, top_n=TOP_N)
                exit_book = get_book_at_time(exit_df, tp1_ms, top_n=TOP_N)

                if not entry_book or not entry_book["bids"] or not entry_book["asks"]:
                    skips += 1
                    coin_results.append({"time": dt.isoformat(), "rate_pct": round(rate*100, 4), "filled": 0, "slip": 0, "net": 0, "status": "no_book"})
                    continue

                result = simulate_settlement(entry_book, exit_book, rate, notional)
                if result is None:
                    skips += 1
                    coin_results.append({"time": dt.isoformat(), "rate_pct": round(rate*100, 4), "filled": 0, "slip": 0, "net": 0, "status": "thin_book"})
                    continue

                if result["is_full"]:
                    full_fills += 1
                elif result["is_partial"]:
                    partial_fills += 1

                coin_net += result["net_profit"]
                coin_results.append({
                    "time": dt.isoformat(),
                    "rate_pct": round(rate*100, 4),
                    "filled": result["filled_notional"],
                    "slip": round(result["entry_slip_pct"] + result["exit_slip_pct"], 4),
                    "net": result["net_profit"],
                    "status": "full" if result["is_full"] else "partial",
                })

            # Coin summary
            print(f"\n{'=' * 80}")
            print(f"{symbol} @ €{base_size} base × {leverage}x = €{notional:,.0f} order")
            print(f"{'=' * 80}")
            print(f"  Full fills: {full_fills}  |  Partial: {partial_fills}  |  Skips: {skips}  |  Total: {len(coin_results)}")
            print(f"  Net P&L:    €{coin_net:,.2f}")
            print(f"  Per trade:  €{coin_net / max(len(coin_results), 1):,.4f}")

            # Print all trades
            print(f"\n  {'Time':<28s} {'Rate%':>7s} {'Filled':>12s} {'Slip%':>8s} {'Net€':>10s} {'Status':>8s}")
            print(f"  {'-'*78}")
            for cr in coin_results:
                print(f"  {cr['time']:<28s} {cr['rate_pct']:>7.3f} {cr['filled']:>12,.2f} {cr['slip']:>8.4f} {cr['net']:>10.4f} {cr['status']:>8s}")

            grand_totals[base_size]["net"] += coin_net
            grand_totals[base_size]["trades"] += len(coin_results)
            grand_totals[base_size]["coins"] += 1

    # Grand totals
    for base_size in BASE_SIZES:
        gt = grand_totals[base_size]
        print(f"\n{'=' * 80}")
        print(f"GRAND TOTAL — €{base_size} base")
        print(f"{'=' * 80}")
        print(f"  Coins traded: {gt['coins']}")
        print(f"  Total trades: {gt['trades']}")
        print(f"  Total net:    €{gt['net']:,.2f}")
        print(f"  Per trade:    €{gt['net'] / max(gt['trades'], 1):,.4f}")

    # Save
    output = {str(s): gt for s, gt in grand_totals.items()}
    with open("backtest_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to backtest_results.json")


if __name__ == "__main__":
    main()
