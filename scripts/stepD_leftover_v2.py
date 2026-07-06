"""
Quick corrected backtest for GUAUSDT only (profitable leftover coin).
Same logic as stepD_backtest_v2.py.
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

COINS = {"GUAUSDT": {"leverage": 5}, "SLXUSDT": {"leverage": 5}, "ZKPUSDT": {"leverage": 5}, "REUSDT": {"leverage": 5}}


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
    slip = entry_filled * entry_slip / 100 + exit_filled * exit_slip / 100
    net = funding - fees - slip + price_pnl
    return {"filled": round(entry_filled,2), "price_pnl": round(price_pnl,4), "funding": round(funding,4),
            "fees": round(fees,4), "slip": round(slip,4), "net": round(net,4), "full": entry_filled >= notional_usd*0.99}

def get_file_path(symbol, dt):
    return f"aster_futures/{dt.strftime('%Y-%m-%d')}/{dt.strftime('%H')}/{symbol}_orderbook.parquet.zst"

def get_combined(downloaded, symbol, dt):
    paths = [get_file_path(symbol, dt), get_file_path(symbol, dt - timedelta(hours=1))]
    dfs = [downloaded[p] for p in paths if p in downloaded]
    return pd.concat(dfs, ignore_index=True) if dfs else None

def main():
    global _file_cache
    if not CHFD_KEY:
        print("ERROR: no key"); sys.exit(1)
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    print("=" * 80)
    print("CORRECTED BACKTEST v2: Leftover coins (GUAUSDT, SLXUSDT, ZKPUSDT, REUSDT)")
    print("=" * 80)

    grand = {"net": 0, "funding": 0, "price_pnl": 0, "trades": 0}

    for symbol, info in COINS.items():
        _file_cache.clear()
        leverage = info["leverage"]
        print(f"\n--- {symbol} ({leverage}x) ---")
        entries = fetch_funding_history(symbol)
        recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
        qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
        print(f"  {len(qualifying)} qualifying in 14d")
        if not qualifying:
            continue

        files_needed = set()
        for e in qualifying:
            dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            files_needed.add(get_file_path(symbol, dt - timedelta(hours=1)))
            files_needed.add(get_file_path(symbol, dt))
            files_needed.add(get_file_path(symbol, dt + timedelta(hours=1)))

        downloaded = {}
        for path in sorted(files_needed):
            df = download_parquet(path)
            if df is not None and not df.empty:
                downloaded[path] = df
            time.sleep(0.15)
        print(f"  Downloaded {len(downloaded)} files")

        for base_size in [500, 250]:
            notional = base_size * leverage
            coin_funding = coin_price = coin_net = 0
            full = partial = skip = 0
            for e in qualifying:
                ts = e["fundingTime"]
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                rate = float(e["fundingRate"])
                entry_df = get_combined(downloaded, symbol, dt - timedelta(minutes=1))
                exit_df = get_combined(downloaded, symbol, dt + timedelta(minutes=1))
                if entry_df is None or exit_df is None:
                    skip += 1; continue
                eb = get_book_at_time(entry_df, ts - 60_000)
                xb = get_book_at_time(exit_df, ts + 60_000)
                if not eb or not xb or not eb["bids"] or not eb["asks"]:
                    skip += 1; continue
                r = simulate_settlement(eb, xb, rate, notional)
                if r is None:
                    skip += 1; continue
                if r["full"]: full += 1
                else: partial += 1
                coin_funding += r["funding"]
                coin_price += r["price_pnl"]
                coin_net += r["net"]
                if base_size == 500:
                    grand["funding"] += r["funding"]
                    grand["price_pnl"] += r["price_pnl"]
                    grand["net"] += r["net"]
                    grand["trades"] += 1

            total = full + partial + skip
            print(f"  €{base_size} ({leverage}x=€{notional:,}): {full}f {partial}p {skip}s | Funding: €{coin_funding:+,.2f} | Price: €{coin_price:+,.2f} | Net: €{coin_net:+,.2f}")

    print(f"\n{'=' * 80}")
    print(f"LEFTOVERS GRAND TOTAL (€500 base)")
    print(f"  Trades: {grand['trades']}  Funding: €{grand['funding']:+,.2f}  Price: €{grand['price_pnl']:+,.2f}  Net: €{grand['net']:+,.2f}")

if __name__ == "__main__":
    main()
