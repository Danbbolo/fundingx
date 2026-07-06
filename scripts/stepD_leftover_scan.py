"""
Quick scan: check which 'interesting' coins from Step 2 have qualifying events in last 14 days.
Then backtest survivors with same logic as stepD.
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

# Candidates from Step 2 top 15 not yet analyzed (avg >= 2.5)
# Already done: LABUSDT, TAIKOUSDT, BIRBUSDT, HUSDT, PIPPINUSDT, COAIUSDT, BEATUSDT, AIAUSDT, HOMEUSDT
CANDIDATES = [
    "FIDAUSDT",    # 4.8 avg
    "TNSRUSDT",    # 4.3
    "ENJUSDT",     # 4.2
    "REUSDT",      # 4.0
    "SLXUSDT",     # 4.0
    "ZKPUSDT",     # 3.8
    "XCNUSDT",     # 3.6
    "STGUSDT",     # 3.6
    "GIGGLEUSDT",  # 3.2
    "BULLAUSDT",   # 3.1
    "AZTECUSDT",   # 3.0
    "0GUSDT",      # 2.8
    "FRAXUSDT",    # 2.8
    "GUAUSDT",     # 2.6
    "ONTUSDT",     # 2.6
    "LIGHTUSDT",   # 2.5
    "REDUSDT",     # 2.5
]


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
    total_usd_spent = 0.0
    for price, qty_base in levels:
        level_usd = price * qty_base
        if level_usd >= remaining_usd:
            base_filled = remaining_usd / price
            total_base += base_filled
            total_usd_spent += remaining_usd
            remaining_usd = 0
            break
        else:
            total_base += qty_base
            total_usd_spent += level_usd
            remaining_usd -= level_usd
    return total_usd_spent, (total_usd_spent / total_base if total_base > 0 else 0), total_base


def simulate_settlement(entry_book, exit_book, settled_rate, notional_usd):
    is_short = settled_rate < 0
    if is_short:
        entry_levels = entry_book["bids"]
        exit_levels = exit_book["asks"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0
    else:
        entry_levels = entry_book["asks"]
        exit_levels = exit_book["bids"]
        best_entry = entry_levels[0][0] if entry_levels else 0
        best_exit = exit_levels[0][0] if exit_levels else 0

    entry_filled, entry_avg, _ = walk_book(entry_levels, notional_usd)
    if entry_filled < notional_usd * 0.20:
        return None

    exit_filled, exit_avg, _ = walk_book(exit_levels, entry_filled)
    entry_slip_pct = abs(entry_avg - best_entry) / best_entry * 100 if best_entry > 0 else 0
    exit_slip_pct = abs(exit_avg - best_exit) / best_exit * 100 if best_exit > 0 else 0

    funding_earned = entry_filled * abs(settled_rate)
    fees = entry_filled * TAKER_FEE_RT
    slip_cost = entry_filled * entry_slip_pct / 100 + exit_filled * exit_slip_pct / 100
    net_profit = funding_earned - fees - slip_cost

    return {
        "filled": round(entry_filled, 2),
        "slip": round(entry_slip_pct + exit_slip_pct, 4),
        "net": round(net_profit, 4),
        "full": entry_filled >= notional_usd * 0.99,
    }


def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"


def get_combined(downloaded, symbol, dt):
    paths = [get_file_path(symbol, dt), get_file_path(symbol, dt - timedelta(hours=1))]
    dfs = [downloaded[p] for p in paths if p in downloaded]
    return pd.concat(dfs, ignore_index=True) if dfs else None


def main():
    print("=" * 80)
    print("SCAN + BACKTEST: Leftover Step 2 candidates")
    print("=" * 80)

    if not CHFD_KEY:
        print("ERROR: CRYPTOHFTDATA_API_KEY not set")
        sys.exit(1)

    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    # Phase 1: quick qualifying check
    print(f"\nPhase 1: Checking {len(CANDIDATES)} coins for qualifying events in last 14 days...")
    print(f"{'Symbol':<16s} {'Total':>6s} {'Qual':>6s} {'Has_CHFD':>10s} {'Status':>12s}")
    print("-" * 55)

    survivors = {}
    for symbol in CANDIDATES:
        entries = fetch_funding_history(symbol)
        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]

        # Check CHFD
        has_chfd = False
        try:
            r = requests.get(f"{CHFD_BASE}/symbols", params={"exchange": "aster_futures", "data_type": "orderbook"}, timeout=10)
            if r.ok:
                has_chfd = symbol in r.json().get("symbols", [])
        except:
            pass

        status = "QUALIFIES" if qualifying and has_chfd else "skip"
        if qualifying and has_chfd:
            survivors[symbol] = qualifying
            status = f"✓ {len(qualifying)}q"
        elif qualifying and not has_chfd:
            status = "no CHFD"
        else:
            status = "0 qual"

        print(f"{symbol:<16s} {len(recent):>6d} {len(qualifying):>6d} {'Yes' if has_chfd else 'No':>10s} {status:>12s}")
        time.sleep(0.1)

    if not survivors:
        print("\nNo survivors. All coins have 0 qualifying events in last 14 days.")
        return

    # Phase 2: backtest survivors
    print(f"\n{'=' * 80}")
    print(f"Phase 2: Backtesting {len(survivors)} surviving coins")
    print(f"{'=' * 80}")

    all_coin_summaries = []
    grand_net_500 = 0
    grand_net_250 = 0
    grand_trades = 0

    for symbol, qualifying in survivors.items():
        global _file_cache
        _file_cache.clear()

        print(f"\n--- {symbol} ({len(qualifying)} qualifying) ---")

        # Assume 5x leverage for new coins
        leverage = 5

        # Build file set
        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))
            files_needed.add(get_file_path(symbol, dt))
            files_needed.add(get_file_path(symbol, dt + timedelta(hours=1)))

        downloaded = {}
        for i, path in enumerate(sorted(files_needed), 1):
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
            time.sleep(0.15)

        # Backtest at €500 base
        for base_size, label in [(500, "€500"), (250, "€250")]:
            notional = base_size * leverage
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
                    continue

                entry_book = get_book_at_time(entry_df, ts - 60_000, top_n=TOP_N)
                exit_book = get_book_at_time(exit_df, ts + 60_000, top_n=TOP_N)

                if not entry_book or not exit_book or not entry_book["bids"] or not entry_book["asks"]:
                    skip += 1
                    continue

                result = simulate_settlement(entry_book, exit_book, rate, notional)
                if result is None:
                    skip += 1
                    continue

                if result["full"]:
                    full += 1
                else:
                    partial += 1
                coin_net += result["net"]
                trades.append(result)

            if label == "€500":
                grand_net_500 += coin_net
                grand_trades += len(trades)
            else:
                grand_net_250 += coin_net

            per_trade = coin_net / max(len(trades), 1)
            print(f"  {label} base ({leverage}x=€{notional:,}): {full}f {partial}p {skip}s | Net: €{coin_net:,.2f} | €{per_trade:,.2f}/trade")

            all_coin_summaries.append({
                "symbol": symbol,
                "base": base_size,
                "notional": notional,
                "full": full,
                "partial": partial,
                "skip": skip,
                "net": round(coin_net, 2),
                "per_trade": round(per_trade, 2),
            })

    # Grand totals
    print(f"\n{'=' * 80}")
    print(f"GRAND TOTAL (new coins only)")
    print(f"{'=' * 80}")
    print(f"  €500 base: €{grand_net_500:,.2f} ({grand_trades} trades)")
    print(f"  €250 base: €{grand_net_250:,.2f}")

    # Save
    with open("stepD_leftover_results.json", "w") as f:
        json.dump(all_coin_summaries, f, indent=2)
    print(f"\nSaved to stepD_leftover_results.json")


if __name__ == "__main__":
    main()
