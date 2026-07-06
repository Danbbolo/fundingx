"""
Independent verification using Aster's kline endpoint (NOT cryptohftdata).
1. Check 10 specific settlements: kline close at T-1, T-0, T+1
2. Compare against both backtest versions' exit prices
3. Across all 123: % with price UP at T+1min vs entry
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

ASTER_BASE = "https://fapi.asterdex.com"
THRESHOLD = 0.0024
LOOKBACK_DAYS = 14
SYMBOL = "LABUSDT"

# 10 specific settlements to verify
DEBUG_SETTLEMENTS = [
    "2026-06-24T12:00:00",
    "2026-06-24T16:00:00",
    "2026-06-26T08:00:00",
    "2026-06-27T17:00:00",
    "2026-06-28T01:00:00",
    "2026-06-29T09:00:00",
    "2026-06-30T08:00:00",
    "2026-07-02T21:00:00",
    "2026-07-03T02:00:00",
    "2026-07-03T11:00:00",
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


def fetch_klines(symbol, start_ms, end_ms, interval="1m", limit=10):
    """Fetch 1m klines. Returns list of [open_time, open, high, low, close, volume, ...]."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    r = requests.get(f"{ASTER_BASE}/fapi/v1/klines", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def load_backtest_trades(filepath):
    """Load v3 backtest trades for comparison."""
    with open(filepath) as f:
        trades = json.load(f)
    # Index by time string
    by_time = {}
    for t in trades:
        if t["coin"] == SYMBOL and t["filled"] > 0:
            by_time[t["time"]] = t
    return by_time


def main():
    print("=" * 90)
    print("INDEPENDENT VERIFICATION: Aster klines vs cryptohftdata backtest")
    print("=" * 90)

    # Load backtest v3 trades for comparison
    v3_trades = load_backtest_trades("backtest_v3_trades.json")

    # Get all qualifying settlements
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    entries = fetch_funding_history(SYMBOL)
    qualifying = [e for e in entries if e["fundingTime"] >= cutoff_ms and abs(float(e["fundingRate"])) >= THRESHOLD]
    qualifying.sort(key=lambda e: e["fundingTime"])
    print(f"  {len(qualifying)} qualifying settlements")

    # ============================================================
    # PART 1: Detailed check on 10 settlements
    # ============================================================
    print(f"\n{'=' * 90}")
    print("PART 1: 10 Specific Settlements — Kline Verification")
    print(f"{'=' * 90}")

    debug_set = set(DEBUG_SETTLEMENTS)

    print(f"\n  {'Settlement':<22s} {'Rate%':>6s} {'T-1min':>10s} {'T+0':>10s} {'T+1min':>10s} {'Dir':>5s} {'v3_exit':>10s} {'Match?':>7s}")
    print(f"  {'-' * 82}")

    for e in qualifying:
        ts_ms = e["fundingTime"]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        dt_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

        if dt_str not in debug_set:
            continue

        rate = float(e["fundingRate"])

        # Fetch klines: T-2min to T+2min (5 candles)
        klines = fetch_klines(SYMBOL, ts_ms - 120_000, ts_ms + 120_000, interval="1m", limit=5)

        if len(klines) < 3:
            print(f"  {dt_str:<22s} {rate*100:>6.3f} INSUFFICIENT KLINES ({len(klines)})")
            continue

        # Klines: [open_time, open, high, low, close, ...]
        # T-1min candle: close of candle before settlement
        # T+0 candle: close of candle at settlement
        # T+1min candle: close of candle after settlement
        kline_times = [k[0] for k in klines]

        # Find the candle that contains settlement time
        # Candles are: T-2, T-1, T+0, T+1, T+2 (each 1 min)
        # We want: close of T-1, close of T+0, close of T+1
        if len(klines) >= 4:
            t_minus_1_close = float(klines[1][4])  # close of 2nd candle (T-1)
            t_plus_0_close = float(klines[2][4])    # close of 3rd candle (T+0, settlement minute)
            t_plus_1_close = float(klines[3][4])    # close of 4th candle (T+1min after)
        else:
            t_minus_1_close = float(klines[0][4])
            t_plus_0_close = float(klines[1][4])
            t_plus_1_close = float(klines[2][4])

        direction = "UP" if t_plus_1_close > t_minus_1_close else "DOWN"

        # Compare with v3 backtest
        v3_exit = v3_trades.get(dt_str, {}).get("exit_price", 0)
        v3_match = ""
        if v3_exit > 0:
            diff_pct = abs(v3_exit - t_plus_1_close) / t_plus_1_close * 100
            v3_match = f"{diff_pct:.3f}%"

        print(f"  {dt_str:<22s} {rate*100:>6.3f} {t_minus_1_close:>10.4f} {t_plus_0_close:>10.4f} {t_plus_1_close:>10.4f} {direction:>5s} {v3_exit:>10.4f} {v3_match:>7s}")

        time.sleep(0.15)

    # ============================================================
    # PART 2: All 123 settlements — price direction at T+1min
    # ============================================================
    print(f"\n{'=' * 90}")
    print("PART 2: All 123 Settlements — Price Direction at T+1min")
    print(f"{'=' * 90}")

    up_count = 0
    down_count = 0
    flat_count = 0
    total_kline_up_pnl = 0
    total_kline_down_pnl = 0
    all_results = []

    for i, e in enumerate(qualifying):
        ts_ms = e["fundingTime"]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        rate = float(e["fundingRate"])

        # Fetch klines
        klines = fetch_klines(SYMBOL, ts_ms - 60_000, ts_ms + 120_000, interval="1m", limit=4)

        if len(klines) < 3:
            flat_count += 1
            all_results.append({"time": dt.isoformat(), "direction": "NO_DATA"})
            time.sleep(0.1)
            continue

        # T-1 close, T+1 close
        t_minus_1_close = float(klines[0][4]) if len(klines) >= 2 else float(klines[0][4])
        t_plus_1_close = float(klines[2][4]) if len(klines) >= 3 else float(klines[-1][4])

        # Direction
        if t_plus_1_close > t_minus_1_close:
            up_count += 1
            direction = "UP"
            total_kline_up_pnl += (t_plus_1_close - t_minus_1_close) / t_minus_1_close * 100
        elif t_plus_1_close < t_minus_1_close:
            down_count += 1
            direction = "DOWN"
            total_kline_down_pnl += (t_plus_1_close - t_minus_1_close) / t_minus_1_close * 100
        else:
            flat_count += 1
            direction = "FLAT"

        all_results.append({
            "time": dt.isoformat(),
            "rate_pct": round(rate * 100, 4),
            "t_minus_1": t_minus_1_close,
            "t_plus_1": t_plus_1_close,
            "change_pct": round((t_plus_1_close - t_minus_1_close) / t_minus_1_close * 100, 4),
            "direction": direction,
        })

        if (i + 1) % 25 == 0:
            print(f"  Processed {i + 1}/{len(qualifying)}...")
        time.sleep(0.1)

    total = up_count + down_count + flat_count
    print(f"\n  Results across {total} settlements:")
    print(f"    Price UP at T+1min:   {up_count:>4d} ({up_count/total*100:.1f}%)")
    print(f"    Price DOWN at T+1min: {down_count:>4d} ({down_count/total*100:.1f}%)")
    print(f"    Flat/No data:         {flat_count:>4d} ({flat_count/total*100:.1f}%)")
    print(f"\n  Avg change when UP:   {total_kline_up_pnl/max(up_count,1):+.4f}%")
    print(f"  Avg change when DOWN: {total_kline_down_pnl/max(down_count,1):+.4f}%")

    # Compare with backtest win rate
    v3_wins = sum(1 for t in v3_trades.values() if t.get("coin") == SYMBOL and t.get("net", 0) > 0)
    v3_total = sum(1 for t in v3_trades.values() if t.get("coin") == SYMBOL and t.get("filled", 0) > 0)
    print(f"\n  Backtest v3 win rate: {v3_wins}/{v3_total} = {v3_wins/v3_total*100:.1f}%")
    print(f"  Kline UP rate:        {up_count}/{total} = {up_count/total*100:.1f}%")

    # Save
    with open("stepD_kline_verification.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to stepD_kline_verification.json")


if __name__ == "__main__":
    main()
