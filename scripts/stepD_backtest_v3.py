"""
CORRECTED Backtest v3: same logic as v2 but saves per-trade JSON for analysis.
Direction: negative rate → LONG (receive), positive rate → SHORT (receive)
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


def simulate_settlement(entry_book, exit_book, settled_rate, notional_usd):
    go_long = settled_rate < 0
    if go_long:
        entry_levels = entry_book["asks"]
        exit_levels = exit_book["bids"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
        direction = "LONG"
    else:
        entry_levels = entry_book["bids"]
        exit_levels = exit_book["asks"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
        direction = "SHORT"

    entry_filled, entry_avg, entry_base = walk_book(entry_levels, notional_usd)
    if entry_filled < notional_usd * 0.20:
        return None

    exit_filled, exit_avg, exit_base = walk_book(exit_levels, entry_filled)

    entry_slip_pct = abs(entry_avg - best_entry) / best_entry * 100 if best_entry > 0 else 0
    exit_slip_pct = abs(exit_avg - best_exit) / best_exit * 100 if best_exit > 0 else 0

    if go_long:
        price_pnl = (exit_avg - entry_avg) * entry_base
    else:
        price_pnl = (entry_avg - exit_avg) * entry_base

    funding_earned = entry_filled * abs(settled_rate)
    fees = entry_filled * TAKER_FEE_RT
    slip_cost = entry_filled * entry_slip_pct / 100 + exit_filled * exit_slip_pct / 100
    net_profit = funding_earned - fees - slip_cost + price_pnl

    return {
        "direction": direction,
        "filled_usd": round(entry_filled, 2),
        "entry_price": round(entry_avg, 6),
        "exit_price": round(exit_avg, 6),
        "entry_slip_pct": round(entry_slip_pct, 4),
        "exit_slip_pct": round(exit_slip_pct, 4),
        "funding_earned": round(funding_earned, 4),
        "fees": round(fees, 4),
        "slip_cost": round(slip_cost, 4),
        "price_pnl": round(price_pnl, 4),
        "net_profit": round(net_profit, 4),
        "is_full": entry_filled >= notional_usd * 0.99,
    }


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def get_combined(downloaded, symbol, dt):
    paths = [get_file_path(symbol, dt), get_file_path(symbol, dt - timedelta(hours=1))]
    dfs = [downloaded[p] for p in paths if p in downloaded]
    return pd.concat(dfs, ignore_index=True) if dfs else None


def main():
    print("=" * 80)
    print("BACKTEST v3: per-trade JSON export")
    print("=" * 80)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    base_size = 500  # single run only
    all_trades = []  # collect every trade for JSON export

    for symbol, info in COINS.items():
        leverage = info["leverage"]
        notional = base_size * leverage
        _file_cache.clear()

        print(f"\n{symbol} — {leverage}x = €{notional:,}")

        entries = fetch_funding_history(symbol)
        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"  {len(qualifying)} qualifying")

        if not qualifying:
            continue

        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))
            files_needed.add(get_file_path(symbol, dt))
            files_needed.add(get_file_path(symbol, dt + timedelta(hours=1)))

        print(f"  Downloading {len(files_needed)} files...")
        downloaded = {}
        for path in sorted(files_needed):
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
            time.sleep(0.15)
        print(f"  Downloaded {len(downloaded)}")

        for e in qualifying:
            ts = e["fundingTime"]
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            rate = float(e["fundingRate"])

            entry_df = get_combined(downloaded, symbol, dt - timedelta(minutes=1))
            exit_df = get_combined(downloaded, symbol, dt + timedelta(minutes=1))

            if entry_df is None or exit_df is None:
                all_trades.append({"coin": symbol, "time": dt.isoformat(), "rate_pct": round(rate*100,4), "direction": "?", "filled": 0, "entry_price": 0, "exit_price": 0, "price_pnl": 0, "funding": 0, "fees": 0, "slip": 0, "net": 0, "status": "no_data"})
                continue

            entry_book = get_book_at_time(entry_df, ts - 60_000, top_n=TOP_N)
            exit_book = get_book_at_time(exit_df, ts + 60_000, top_n=TOP_N)

            if not entry_book or not exit_book or not entry_book["bids"] or not entry_book["asks"]:
                all_trades.append({"coin": symbol, "time": dt.isoformat(), "rate_pct": round(rate*100,4), "direction": "?", "filled": 0, "entry_price": 0, "exit_price": 0, "price_pnl": 0, "funding": 0, "fees": 0, "slip": 0, "net": 0, "status": "no_book"})
                continue

            result = simulate_settlement(entry_book, exit_book, rate, notional)
            if result is None:
                all_trades.append({"coin": symbol, "time": dt.isoformat(), "rate_pct": round(rate*100,4), "direction": "?", "filled": 0, "entry_price": 0, "exit_price": 0, "price_pnl": 0, "funding": 0, "fees": 0, "slip": 0, "net": 0, "status": "thin"})
                continue

            all_trades.append({
                "coin": symbol,
                "time": dt.isoformat(),
                "rate_pct": round(rate * 100, 4),
                "direction": result["direction"],
                "filled": result["filled_usd"],
                "entry_price": result["entry_price"],
                "exit_price": result["exit_price"],
                "price_pnl": result["price_pnl"],
                "funding": result["funding_earned"],
                "fees": result["fees"],
                "slip": result["slip_cost"],
                "net": result["net_profit"],
                "status": "full" if result["is_full"] else "partial",
            })

    # Verify counts
    print(f"\n{'=' * 80}")
    print("TRADE COUNT VERIFICATION")
    for symbol in COINS:
        count = sum(1 for t in all_trades if t["coin"] == symbol and t["filled"] > 0)
        expected = COINS[symbol].get("expected", "?")
        print(f"  {symbol}: {count} filled trades")

    # Summary
    filled = [t for t in all_trades if t["filled"] > 0]
    print(f"\n  Total filled: {len(filled)}")
    print(f"  Net: €{sum(t['net'] for t in filled):+,.2f}")
    print(f"  Funding: €{sum(t['funding'] for t in filled):+,.2f}")
    print(f"  Price P&L: €{sum(t['price_pnl'] for t in filled):+,.2f}")

    # Save per-trade JSON
    with open("backtest_v3_trades.json", "w") as f:
        json.dump(all_trades, f, indent=2)
    print(f"\nSaved {len(all_trades)} trades to backtest_v3_trades.json")


if __name__ == "__main__":
    main()
