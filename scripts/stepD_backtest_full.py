"""
Full-history drift vs funding analysis for LABUSDT using Aster klines only.
All qualifying negative-funding settlements (~83 days), not just 14-day window.
Split by weekly regime (uptrend/flat/downtrend).
"""
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

ASTER_BASE = "https://fapi.asterdex.com"
SYMBOL = "LABUSDT"
THRESHOLD = 0.0024
LEVERAGE = 10
BASE_SIZE = 500
NOTIONAL = BASE_SIZE * LEVERAGE


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
    """Get the 1m kline that contains target_ms, return its close price."""
    klines = requests.get(f"{ASTER_BASE}/fapi/v1/klines", params={
        "symbol": symbol, "interval": "1m",
        "startTime": target_ms - 60_000, "endTime": target_ms + 60_000, "limit": 3,
    }, timeout=10).json()
    if not klines:
        return None
    # Find the candle whose open_time is closest to target
    best = min(klines, key=lambda k: abs(k[0] - target_ms))
    return float(best[4])  # close price


def fetch_weekly_closes(symbol, start_ms, end_ms):
    """Fetch weekly candles to determine regime."""
    klines = requests.get(f"{ASTER_BASE}/fapi/v1/klines", params={
        "symbol": symbol, "interval": "1w",
        "startTime": start_ms, "endTime": end_ms, "limit": 100,
    }, timeout=10).json()
    return [(k[0], float(k[4])) for k in klines]  # (open_time, close)


def get_regime(weekly_closes, settlement_ms):
    """Determine if LABUSDT was in uptrend/flat/downtrend that week."""
    if len(weekly_closes) < 2:
        return "unknown"
    # Find the weekly candle containing this settlement
    for i, (open_time, close) in enumerate(weekly_closes):
        week_end = open_time + 7 * 24 * 3600 * 1000
        if open_time <= settlement_ms < week_end:
            # Compare this week's close to previous week's close
            prev_close = weekly_closes[i - 1][1] if i > 0 else close
            if prev_close == 0:
                return "unknown"
            change_pct = (close - prev_close) / prev_close * 100
            if change_pct > 2:
                return "uptrend"
            elif change_pct < -2:
                return "downtrend"
            else:
                return "flat"
    return "unknown"


def main():
    print("=" * 80)
    print("LABUSDT Full-History: Drift vs Funding (Aster klines only)")
    print("=" * 80)

    # 1. Get all funding history
    print("\n[*] Fetching full funding history...")
    all_entries = fetch_all_funding(SYMBOL)
    all_entries.sort(key=lambda e: e["fundingTime"])
    print(f"    Total entries: {len(all_entries)}")

    if not all_entries:
        print("    No data"); return

    first_ts = all_entries[0]["fundingTime"]
    last_ts = all_entries[-1]["fundingTime"]
    span_days = (last_ts - first_ts) / 86400000
    print(f"    Span: {datetime.fromtimestamp(first_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(last_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d')} ({span_days:.0f} days)")

    # 2. Filter to qualifying negative-funding settlements
    qualifying = [e for e in all_entries if float(e["fundingRate"]) <= -THRESHOLD]
    print(f"    Qualifying (rate <= -{THRESHOLD}): {len(qualifying)}")
    print(f"    (Positive qualifying skipped — strategy goes LONG on negative)")

    # 3. Get weekly candles for regime detection
    print("\n[*] Fetching weekly candles for regime detection...")
    weekly_closes = fetch_weekly_closes(SYMBOL, first_ts, last_ts + 7*86400000)
    print(f"    {len(weekly_closes)} weekly candles")

    # 4. For each qualifying settlement, get kline prices
    print(f"\n[*] Processing {len(qualifying)} settlements...")
    results = []
    for i, e in enumerate(qualifying):
        ts_ms = e["fundingTime"]
        rate = float(e["fundingRate"])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

        # Get close prices at T-1min and T+1min
        price_t_minus_1 = fetch_kline_close(SYMBOL, ts_ms - 60_000)
        price_t_plus_1 = fetch_kline_close(SYMBOL, ts_ms + 60_000)

        if price_t_minus_1 is None or price_t_plus_1 is None:
            time.sleep(0.1)
            continue

        # Direction: LONG (negative rate = longs receive)
        # Funding earned: notional * |rate|
        funding_eur = NOTIONAL * abs(rate)
        # Price P&L: (exit - entry) * (notional / entry_price)
        position_base = NOTIONAL / price_t_minus_1
        price_pnl_eur = (price_t_plus_1 - price_t_minus_1) * position_base
        drift_pct = (price_t_plus_1 - price_t_minus_1) / price_t_minus_1 * 100

        # Regime
        regime = get_regime(weekly_closes, ts_ms)

        results.append({
            "time": dt.strftime("%Y-%m-%d %H:%M"),
            "rate_pct": round(rate * 100, 4),
            "price_t1": price_t_minus_1,
            "price_t1_plus": price_t_plus_1,
            "drift_pct": round(drift_pct, 4),
            "funding_eur": round(funding_eur, 2),
            "price_pnl_eur": round(price_pnl_eur, 2),
            "net_eur": round(funding_eur + price_pnl_eur, 2),
            "regime": regime,
        })

        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(qualifying)}...")
        time.sleep(0.1)

    print(f"    Processed {len(results)} settlements")

    # ============================================================
    # OUTPUT A: Overall
    # ============================================================
    print(f"\n{'=' * 80}")
    print("(A) OVERALL — Total Funding vs Total Drift")
    print(f"{'=' * 80}")

    total_funding = sum(r["funding_eur"] for r in results)
    total_price = sum(r["price_pnl_eur"] for r in results)
    total_net = sum(r["net_eur"] for r in results)
    up_count = sum(1 for r in results if r["drift_pct"] > 0)
    down_count = sum(1 for r in results if r["drift_pct"] <= 0)

    print(f"\n  Settlements:     {len(results)}")
    print(f"  Funding total:   €{total_funding:+,.2f}")
    print(f"  Price P&L total: €{total_price:+,.2f}")
    print(f"  NET:             €{total_net:+,.2f}")
    print(f"  Per settlement:  €{total_net/len(results):+.2f}")
    print(f"\n  Price UP after:   {up_count} ({up_count/len(results)*100:.1f}%)")
    print(f"  Price DOWN after: {down_count} ({down_count/len(results)*100:.1f}%)")
    print(f"  Avg drift when UP:   {sum(r['drift_pct'] for r in results if r['drift_pct'] > 0) / max(up_count,1):+.4f}%")
    print(f"  Avg drift when DOWN: {sum(r['drift_pct'] for r in results if r['drift_pct'] <= 0) / max(down_count,1):+.4f}%")

    # ============================================================
    # OUTPUT B: By regime
    # ============================================================
    print(f"\n{'=' * 80}")
    print("(B) BY REGIME — Uptrend / Flat / Downtrend weeks")
    print(f"{'=' * 80}")

    by_regime = defaultdict(list)
    for r in results:
        by_regime[r["regime"]].append(r)

    print(f"\n  {'Regime':<12s} {'N':>5s} {'Funding':>10s} {'PricePnL':>10s} {'Net':>10s} {'Net/Trade':>10s} {'UP%':>6s} {'DOWN%':>6s}")
    print(f"  {'-' * 72}")

    for regime in ["uptrend", "flat", "downtrend", "unknown"]:
        trs = by_regime.get(regime, [])
        if not trs:
            continue
        n = len(trs)
        fund = sum(r["funding_eur"] for r in trs)
        price = sum(r["price_pnl_eur"] for r in trs)
        net = sum(r["net_eur"] for r in trs)
        up = sum(1 for r in trs if r["drift_pct"] > 0)
        down = n - up
        print(f"  {regime:<12s} {n:>5d} {fund:>+10.2f} {price:>+10.2f} {net:>+10.2f} {net/n:>+10.2f} {up/n*100:>5.1f}% {down/n*100:>5.1f}%")

    # Also show weekly breakdown
    print(f"\n  Weekly breakdown:")
    print(f"  {'Week':<14s} {'Regime':<10s} {'N':>4s} {'Funding':>9s} {'Price':>9s} {'Net':>9s}")
    print(f"  {'-' * 58}")

    weekly = defaultdict(list)
    for r in results:
        dt = datetime.strptime(r["time"], "%Y-%m-%d %H:%M")
        week_key = dt.strftime("%Y-W%W")
        weekly[week_key].append(r)

    for week_key in sorted(weekly.keys()):
        trs = weekly[week_key]
        n = len(trs)
        fund = sum(r["funding_eur"] for r in trs)
        price = sum(r["price_pnl_eur"] for r in trs)
        net = sum(r["net_eur"] for r in trs)
        regime = trs[0]["regime"]
        print(f"  {week_key:<14s} {regime:<10s} {n:>4d} {fund:>+9.2f} {price:>+9.2f} {net:>+9.2f}")


if __name__ == "__main__":
    main()
