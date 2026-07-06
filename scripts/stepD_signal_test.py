"""
Signal test: is post-settlement down-drift universal or a LAB artifact?
For all qualifying coins: price change at T-1→T+1, T+5, T+15.
Plus control: same stats at random non-settlement hours.
Aster klines only.
"""
import random
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

ASTER_BASE = "https://fapi.asterdex.com"
THRESHOLD = 0.0024
LOOKBACK_DAYS = 60

COINS = [
    "LABUSDT", "PIPPINUSDT", "GUAUSDT", "COAIUSDT", "TAIKOUSDT",
    "SLXUSDT", "BEATUSDT", "HUSDT", "BIRBUSDT", "REUSDT",
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
        time.sleep(0.08)
    return all_entries


def fetch_kline_close(symbol, target_ms):
    """Get close price of the 1m candle containing target_ms."""
    try:
        klines = requests.get(f"{ASTER_BASE}/fapi/v1/klines", params={
            "symbol": symbol, "interval": "1m",
            "startTime": target_ms - 60_000, "endTime": target_ms + 60_000, "limit": 3,
        }, timeout=10).json()
    except:
        return None
    if not klines:
        return None
    best = min(klines, key=lambda k: abs(k[0] - target_ms))
    return float(best[4])


def compute_drift(symbol, reference_ms, horizons_min):
    """Get price at reference_ms, then at reference_ms + each horizon. Returns dict of drifts."""
    price_ref = fetch_kline_close(symbol, reference_ms)
    if price_ref is None or price_ref == 0:
        return None
    time.sleep(0.08)
    drifts = {}
    for h in horizons_min:
        price_h = fetch_kline_close(symbol, reference_ms + h * 60_000)
        if price_h is not None:
            drifts[h] = (price_h - price_ref) / price_ref * 100
        time.sleep(0.08)
    return drifts


def get_control_hours(qualifying_ts_list, lookback_days, n_samples=50):
    """Generate random non-settlement hours as control."""
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    settlement_set = set(qualifying_ts_list)

    # Generate random timestamps, skip if within 2h of any settlement
    controls = []
    attempts = 0
    while len(controls) < n_samples and attempts < n_samples * 10:
        attempts += 1
        rand_ms = random.randint(cutoff_ms, now_ms)
        # Round to nearest hour
        rand_ms = (rand_ms // 3600000) * 3600000
        # Skip if near a settlement
        if any(abs(rand_ms - s) < 7200000 for s in settlement_set):
            continue
        controls.append(rand_ms)
    return controls


def analyze_drifts(drift_list, horizons_min):
    """Compute stats from a list of drift dicts."""
    stats = {}
    for h in horizons_min:
        vals = [d[h] for d in drift_list if h in d and d[h] is not None]
        if not vals:
            stats[h] = {"n": 0, "pct_down": 0, "median": 0, "mean": 0}
            continue
        vals.sort()
        n = len(vals)
        down = sum(1 for v in vals if v < 0)
        stats[h] = {
            "n": n,
            "pct_down": round(down / n * 100, 1),
            "median": round(vals[n // 2], 4),
            "mean": round(sum(vals) / n, 4),
        }
    return stats


def main():
    print("=" * 90)
    print("SIGNAL TEST: Post-settlement drift — universal or LAB artifact?")
    print("Aster klines only. Horizons: T+1, T+5, T+15 min.")
    print("=" * 90)

    horizons = [1, 5, 15]
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)

    all_results = {}

    for coin in COINS:
        print(f"\n--- {coin} ---")

        # Get qualifying negative-funding settlements
        entries = fetch_funding_history(coin)
        qualifying = [e for e in entries if e["fundingTime"] >= cutoff_ms and float(e["fundingRate"]) <= -THRESHOLD]
        qualifying.sort(key=lambda e: e["fundingTime"])
        print(f"  Qualifying (rate <= -{THRESHOLD}): {len(qualifying)}")

        if len(qualifying) < 3:
            print(f"  Too few — skipping")
            all_results[coin] = {"n_settlement": 0, "n_control": 0, "settlement": None, "control": None}
            continue

        # Settlement drifts
        settlement_drifts = []
        for i, e in enumerate(qualifying):
            ts_ms = e["fundingTime"]
            drifts = compute_drift(coin, ts_ms, horizons)
            if drifts:
                settlement_drifts.append(drifts)
            if (i + 1) % 20 == 0:
                print(f"    Settlement {i + 1}/{len(qualifying)}...")

        print(f"  Settlement data: {len(settlement_drifts)} points")

        # Control: random non-settlement hours
        settlement_ts_list = [e["fundingTime"] for e in qualifying]
        control_hours = get_control_hours(settlement_ts_list, LOOKBACK_DAYS, n_samples=50)
        control_drifts = []
        for ts_ms in control_hours:
            drifts = compute_drift(coin, ts_ms, horizons)
            if drifts:
                control_drifts.append(drifts)
        print(f"  Control data: {len(control_drifts)} points")

        # Analyze
        s_stats = analyze_drifts(settlement_drifts, horizons)
        c_stats = analyze_drifts(control_drifts, horizons)

        all_results[coin] = {
            "n_settlement": len(settlement_drifts),
            "n_control": len(control_drifts),
            "settlement": s_stats,
            "control": c_stats,
        }

    # ============================================================
    # OUTPUT
    # ============================================================
    print(f"\n{'=' * 90}")
    print("SETTLEMENT DRIFT (price change T-1 → T+X)")
    print(f"{'=' * 90}")

    header = f"  {'Coin':<16s} {'N':>4s}"
    for h in horizons:
        header += f" │ T+{h} Down% {'':>1s} T+{h} Med% {'':>1s}"
    print(f"\n{header}")
    print(f"  {'-' * 85}")

    for coin in COINS:
        r = all_results[coin]
        if r["n_settlement"] == 0:
            print(f"  {coin:<16s} {'—':>4s}   skipped")
            continue
        s = r["settlement"]
        line = f"  {coin:<16s} {r['n_settlement']:>4d}"
        for h in horizons:
            line += f" │ {s[h]['pct_down']:>6.1f}%  {s[h]['median']:>+7.4f}%"
        print(line)

    # Control
    print(f"\n  CONTROL (random non-settlement hours)")
    print(f"  {'-' * 85}")
    for coin in COINS:
        r = all_results[coin]
        if r["n_control"] == 0:
            continue
        c = r["control"]
        line = f"  {coin:<16s} {r['n_control']:>4d}"
        for h in horizons:
            line += f" │ {c[h]['pct_down']:>6.1f}%  {c[h]['median']:>+7.4f}%"
        print(line)

    # Signal vs artifact
    print(f"\n{'=' * 90}")
    print("SIGNAL vs ARTIFACT")
    print(f"{'=' * 90}")
    print(f"\n  {'Coin':<16s} {'Settl_Down%':>12s} {'Ctrl_Down%':>12s} {'Delta':>8s} {'Signal?':>10s}")
    print(f"  {'-' * 62}")

    for coin in COINS:
        r = all_results[coin]
        if r["n_settlement"] == 0 or r["n_control"] == 0:
            continue
        # Use T+1min as primary signal
        s_down = r["settlement"][1]["pct_down"]
        c_down = r["control"][1]["pct_down"]
        delta = s_down - c_down
        if delta > 10:
            signal = "YES ✓"
        elif delta > 5:
            signal = "WEAK"
        elif delta > -5:
            signal = "NOISE"
        else:
            signal = "REVERSED"
        print(f"  {coin:<16s} {s_down:>11.1f}% {c_down:>11.1f}% {delta:>+7.1f}% {signal:>10s}")


if __name__ == "__main__":
    random.seed(42)
    main()
