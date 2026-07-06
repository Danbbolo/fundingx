"""
Contradiction resolver:
1. LAB 85.3% vs 50.8% — why 191 settlements in both 262-day and 60-day windows?
2. Control validity — rebuild with 200 samples per coin.
"""
import random
import time
from datetime import datetime, timezone, timedelta

import requests

ASTER_BASE = "https://fapi.asterdex.com"
THRESHOLD = 0.0024
LOOKBACK_60 = 60
LOOKBACK_FULL = 999  # everything available


def fetch_all_funding(symbol):
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


def fetch_kline_close(symbol, target_ms):
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


def main():
    random.seed(42)

    # ============================================================
    # CONTRADICTION 1: LAB 85.3% vs 50.8%
    # ============================================================
    print("=" * 90)
    print("CONTRADICTION 1: LABUSDT 85.3% vs 50.8%")
    print("=" * 90)

    entries = fetch_all_funding("LABUSDT")
    entries.sort(key=lambda e: e["fundingTime"])

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_60 = now_ms - 60 * 86400000
    cutoff_full = entries[0]["fundingTime"]  # everything

    # Qualifying: negative rate AND |rate| >= threshold
    qual_full_neg = [e for e in entries if float(e["fundingRate"]) <= -THRESHOLD]
    qual_full_any = [e for e in entries if abs(float(e["fundingRate"])) >= THRESHOLD]

    qual_60_neg = [e for e in qual_full_neg if e["fundingTime"] >= cutoff_60]
    qual_60_any = [e for e in qual_full_any if e["fundingTime"] >= cutoff_60]

    full_span = (entries[-1]["fundingTime"] - entries[0]["fundingTime"]) / 86400000
    span_60 = 60

    print(f"\n  Full history:")
    print(f"    Entries: {len(entries)}")
    print(f"    Date range: {datetime.fromtimestamp(entries[0]['fundingTime']/1000, tz=timezone.utc).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(entries[-1]['fundingTime']/1000, tz=timezone.utc).strftime('%Y-%m-%d')} ({full_span:.0f} days)")
    print(f"    Qualifying (rate <= -{THRESHOLD}): {len(qual_full_neg)}")
    print(f"    Qualifying (|rate| >= {THRESHOLD}): {len(qual_full_any)}")

    print(f"\n  60-day window:")
    cutoff_dt = datetime.fromtimestamp(cutoff_60 / 1000, tz=timezone.utc)
    print(f"    Cutoff: {cutoff_dt.strftime('%Y-%m-%d')}")
    print(f"    Qualifying (rate <= -{THRESHOLD}): {len(qual_60_neg)}")
    print(f"    Qualifying (|rate| >= {THRESHOLD}): {len(qual_60_any)}")

    # CRITICAL QUESTION: are they the same set?
    full_ts_set = set(e["fundingTime"] for e in qual_full_neg)
    sixty_ts_set = set(e["fundingTime"] for e in qual_60_neg)
    overlap = full_ts_set & sixty_ts_set
    only_in_full = full_ts_set - sixty_ts_set
    only_in_60 = sixty_ts_set - full_ts_set

    print(f"\n  Set comparison (negative qualifying only):")
    print(f"    Full window timestamps: {len(full_ts_set)}")
    print(f"    60-day timestamps: {len(sixty_ts_set)}")
    print(f"    Overlap: {len(overlap)}")
    print(f"    Only in full (not in 60d): {len(only_in_full)}")
    print(f"    Only in 60d (not in full): {len(only_in_60)}")

    # Print first 10 side by side
    print(f"\n  First 10 qualifying (negative) — full window:")
    for e in qual_full_neg[:10]:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')}  rate={float(e['fundingRate'])*100:.4f}%")

    print(f"\n  First 10 qualifying (negative) — 60-day window:")
    for e in qual_60_neg[:10]:
        dt = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        print(f"    {dt.strftime('%Y-%m-%d %H:%M')}  rate={float(e['fundingRate'])*100:.4f}%")

    # Check: does the signal test use negative-only or absolute?
    # The signal test script: rate <= -THRESHOLD (negative only)
    # The full-history script: rate <= -THRESHOLD (negative only)
    # Both use negative-only. But 191 vs 191...
    # If full window has 191 and 60-day also has 191, then all qualifying
    # settlements are within the last 60 days! Let's verify:
    if len(qual_full_neg) == len(qual_60_neg):
        print(f"\n  *** SAME COUNT: {len(qual_full_neg)} == {len(qual_60_neg)} ***")
        print(f"  This means ALL qualifying negative settlements are within the last 60 days!")
        print(f"  The 262-day window found nothing outside 60 days.")
        oldest_qual = datetime.fromtimestamp(qual_full_neg[0]["fundingTime"]/1000, tz=timezone.utc)
        print(f"  Oldest qualifying: {oldest_qual.strftime('%Y-%m-%d %H:%M')}")
    else:
        print(f"\n  Different counts: full={len(qual_full_neg)}, 60d={len(qual_60_neg)}")
        print(f"  The sets ARE different.")

    # Hand-check 5 settlements against raw klines
    print(f"\n  HAND-CHECK: 5 settlements, kline T-1 close vs T+1 close")
    print(f"  {'Settlement':<22s} {'Rate%':>7s} {'T-1':>10s} {'T+1':>10s} {'Change':>8s} {'Down?':>6s}")
    print(f"  {'-' * 60}")

    check_settlements = qual_full_neg[:5]
    for e in check_settlements:
        ts_ms = e["fundingTime"]
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        rate = float(e["fundingRate"])

        p1 = fetch_kline_close("LABUSDT", ts_ms - 60_000)
        p2 = fetch_kline_close("LABUSDT", ts_ms + 60_000)

        if p1 and p2:
            change = (p2 - p1) / p1 * 100
            down = "YES" if change < 0 else "NO"
            print(f"  {dt.strftime('%Y-%m-%d %H:%M'):<22s} {rate*100:>7.4f} {p1:>10.4f} {p2:>10.4f} {change:>+8.4f}% {down:>6s}")
        else:
            print(f"  {dt.strftime('%Y-%m-%d %H:%M'):<22s} {rate*100:>7.4f} KLINE DATA MISSING")
        time.sleep(0.15)

    # ============================================================
    # CONTRADICTION 2: Rebuild controls with 200 samples
    # ============================================================
    print(f"\n{'=' * 90}")
    print("CONTRADICTION 2: Rebuild controls with 200 samples per coin")
    print(f"{'=' * 90}")

    COINS = ["LABUSDT", "GUAUSDT", "TAIKOUSDT", "SLXUSDT", "HUSDT", "REUSDT"]
    horizons = [1, 5, 15]

    for coin in COINS:
        print(f"\n--- {coin} ---")

        # Get all funding entries for this coin
        if coin == "LABUSDT":
            coin_entries = entries  # already fetched
        else:
            coin_entries = fetch_all_funding(coin)
            coin_entries.sort(key=lambda e: e["fundingTime"])

        if not coin_entries:
            print("  No data"); continue

        # Qualifying negative settlements (last 60 days)
        cutoff_60 = now_ms - 60 * 86400000
        qualifying = [e for e in coin_entries if e["fundingTime"] >= cutoff_60 and float(e["fundingRate"]) <= -THRESHOLD]
        qualifying.sort(key=lambda e: e["fundingTime"])
        settlement_ts_set = set(e["fundingTime"] for e in qualifying)
        print(f"  Qualifying settlements: {len(qualifying)}")

        # Settlement drifts
        s_drifts = {h: [] for h in horizons}
        for e in qualifying:
            ts_ms = e["fundingTime"]
            p_ref = fetch_kline_close(coin, ts_ms - 60_000)
            if p_ref is None or p_ref == 0:
                time.sleep(0.08); continue
            for h in horizons:
                p_h = fetch_kline_close(coin, ts_ms + h * 60_000)
                if p_h is not None:
                    s_drifts[h].append((p_h - p_ref) / p_ref * 100)
                time.sleep(0.08)
            time.sleep(0.05)

        # Control: 200 random non-settlement hours
        first_ts = coin_entries[0]["fundingTime"]
        control_candidates = []
        attempts = 0
        while len(control_candidates) < 200 and attempts < 2000:
            attempts += 1
            rand_ms = random.randint(max(first_ts, cutoff_60), now_ms)
            rand_ms = (rand_ms // 3600000) * 3600000  # round to hour
            # Skip if within 2h of any settlement or any funding settlement (any rate)
            all_funding_ts = set(e["fundingTime"] for e in coin_entries if e["fundingTime"] >= cutoff_60)
            if any(abs(rand_ms - s) < 7200000 for s in all_funding_ts):
                continue
            control_candidates.append(rand_ms)

        print(f"  Control samples: {len(control_candidates)} (from {attempts} attempts)")

        c_drifts = {h: [] for h in horizons}
        for ts_ms in control_candidates:
            p_ref = fetch_kline_close(coin, ts_ms - 60_000)
            if p_ref is None or p_ref == 0:
                time.sleep(0.08); continue
            for h in horizons:
                p_h = fetch_kline_close(coin, ts_ms + h * 60_000)
                if p_h is not None:
                    c_drifts[h].append((p_h - p_ref) / p_ref * 100)
                time.sleep(0.08)
            time.sleep(0.05)

        # Print results
        print(f"\n  Settlement drift:")
        for h in horizons:
            vals = sorted(s_drifts[h])
            n = len(vals)
            if n == 0:
                print(f"    T+{h}: N=0")
                continue
            down = sum(1 for v in vals if v < 0)
            med = vals[n // 2]
            print(f"    T+{h}: N={n}, down={down} ({down/n*100:.1f}%), median={med:+.4f}%")

        print(f"  Control drift:")
        for h in horizons:
            vals = sorted(c_drifts[h])
            n = len(vals)
            if n == 0:
                print(f"    T+{h}: N=0")
                continue
            down = sum(1 for v in vals if v < 0)
            med = vals[n // 2]
            print(f"    T+{h}: N={n}, down={down} ({down/n*100:.1f}%), median={med:+.4f}%")

        # Signal vs artifact at T+1
        s_vals = s_drifts[1]
        c_vals = c_drifts[1]
        if s_vals and c_vals:
            s_down_pct = sum(1 for v in s_vals if v < 0) / len(s_vals) * 100
            c_down_pct = sum(1 for v in c_vals if v < 0) / len(c_vals) * 100
            delta = s_down_pct - c_down_pct
            print(f"  SIGNAL (T+1): settlement={s_down_pct:.1f}% down, control={c_down_pct:.1f}% down, delta={delta:+.1f}%")


if __name__ == "__main__":
    main()
