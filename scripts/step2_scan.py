"""
Step 2: Scan all Aster Pro-mode USDT perpetuals for qualifying funding events.

Per coin:
  1. Pull full available funding rate history (paginated).
  2. Detect real funding interval = mode of time gaps.
  3. Count qualifying events: |rate| >= THRESHOLD.
  4. Rolling 7-day window frequency: min / max / average.

Output: CSV sorted by freq_avg descending.
"""

import csv
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

# ============================================================
# CONFIG
# ============================================================
BASE_URL = "https://fapi.asterdex.com"
THRESHOLD = 0.0024  # decimal — 0.24% (from Step 1)
LIMIT = 1000        # max per request
SLEEP = 0.15        # seconds between API calls (rate limit safety)
WINDOW_DAYS = 7
SAMPLE_SYMBOL = "BTCUSDT"  # symbol for raw response verification

# ============================================================
# HELPERS
# ============================================================

def fetch_funding_history(symbol: str) -> list[dict]:
    """Paginate through all available funding rate history for a symbol."""
    all_entries = []
    end_time = None

    while True:
        params = {"symbol": symbol, "limit": LIMIT}
        if end_time is not None:
            params["endTime"] = end_time

        try:
            r = requests.get(f"{BASE_URL}/fapi/v1/fundingRate", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [WARN] {symbol}: API error — {e}", file=sys.stderr)
            break

        if not data:
            break

        all_entries.extend(data)

        # Stop if we got fewer than LIMIT (no more history)
        if len(data) < LIMIT:
            break

        # Use the oldest entry's time as the next endTime (exclusive)
        end_time = data[0]["fundingTime"] - 1

        time.sleep(SLEEP)

    return all_entries


def detect_interval(entries: list[dict]) -> float:
    """Detect real funding interval in hours from mode of time gaps."""
    if len(entries) < 2:
        return 0.0

    times = sorted(e["fundingTime"] for e in entries)
    gaps_ms = [times[i + 1] - times[i] for i in range(len(times) - 1)]

    # Filter out zero/negative gaps (duplicates)
    gaps_ms = [g for g in gaps_ms if g > 0]
    if not gaps_ms:
        return 0.0

    # Mode of gaps
    most_common_gap_ms, _ = Counter(gaps_ms).most_common(1)[0]
    interval_h = round(most_common_gap_ms / 3_600_000, 1)
    return interval_h


def rolling_window_frequencies(entries: list[dict], threshold: float) -> list[float]:
    """
    Count qualifying events per rolling 7-day window.
    Returns list of qualifying-event counts per window.
    """
    if not entries:
        return []

    # Sort by time
    sorted_entries = sorted(entries, key=lambda e: e["fundingTime"])
    times = [e["fundingTime"] for e in sorted_entries]
    rates = [abs(float(e["fundingRate"])) for e in sorted_entries]

    window_ms = WINDOW_DAYS * 24 * 3_600_000  # 7 days in ms
    counts = []

    # Slide window across the full history
    i = 0
    for j in range(len(sorted_entries)):
        # Advance left pointer
        while times[j] - times[i] > window_ms:
            i += 1
        # Count qualifying in window [i..j]
        window_quals = sum(1 for k in range(i, j + 1) if rates[k] >= threshold)
        counts.append(window_quals)

    return counts


def scan_symbol(symbol: str, print_raw: bool = False) -> dict | None:
    """Full scan for one symbol. Returns result dict or None."""
    entries = fetch_funding_history(symbol)

    if not entries:
        return None

    # Print raw for verification
    if print_raw:
        print(f"\n{'=' * 60}")
        print(f"RAW RESPONSE — {symbol} (first 5 entries)")
        print(f"{'=' * 60}")
        for e in entries[:5]:
            rate_dec = float(e["fundingRate"])
            rate_pct = rate_dec * 100
            ts = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
            print(f"  fundingTime : {e['fundingTime']}  ({ts.isoformat()})")
            print(f"  fundingRate : {e['fundingRate']}  (decimal) = {rate_pct:.6f}%")
            print()

    interval_h = detect_interval(entries)
    total_events = len(entries)

    # Qualifying events
    rates = [abs(float(e["fundingRate"])) for e in entries]
    qualifying = sum(1 for r in rates if r >= THRESHOLD)

    # Rolling 7-day window frequencies
    window_counts = rolling_frequencies = rolling_window_frequencies(entries, THRESHOLD)

    freq_min = min(rolling_frequencies) if rolling_frequencies else 0
    freq_max = max(rolling_frequencies) if rolling_frequencies else 0
    freq_avg = round(sum(rolling_frequencies) / len(rolling_frequencies), 2) if rolling_frequencies else 0

    # Biggest single rate
    biggest_rate = max(rates) if rates else 0

    return {
        "symbol": symbol,
        "interval_h": interval_h,
        "total_events": total_events,
        "qualifying": qualifying,
        "freq_min": freq_min,
        "freq_max": freq_max,
        "freq_avg": freq_avg,
        "biggest_single_rate": biggest_rate,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("STEP 2: Full Funding Rate Scanner")
    print(f"Threshold: {THRESHOLD} (decimal) = {THRESHOLD * 100}%")
    print(f"Rolling window: {WINDOW_DAYS} days")
    print("=" * 60)

    # 1. Get all USDT perp symbols
    print("\n[*] Fetching all USDT perpetual symbols...")
    r = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=15)
    r.raise_for_status()
    all_symbols = sorted([
        s["symbol"] for s in r.json()["symbols"]
        if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    ])
    print(f"    Found {len(all_symbols)} trading pairs")

    # 2. Print raw response for one sample coin
    print(f"\n[*] Fetching raw funding history for {SAMPLE_SYMBOL} (verification)...")
    _ = scan_symbol(SAMPLE_SYMBOL, print_raw=True)

    # 3. Scan all coins
    print(f"\n{'=' * 60}")
    print(f"[*] Scanning all {len(all_symbols)} pairs...")
    print(f"{'=' * 60}")

    results = []
    for idx, symbol in enumerate(all_symbols, 1):
        pct = idx / len(all_symbols) * 100
        print(f"  [{idx:3d}/{len(all_symbols)}] {symbol:<20s} ", end="", flush=True)

        result = scan_symbol(symbol, print_raw=False)
        if result:
            results.append(result)
            print(
                f"int={result['interval_h']}h  "
                f"events={result['total_events']:>5d}  "
                f"qual={result['qualifying']:>4d}  "
                f"avg={result['freq_avg']:.1f}"
            )
        else:
            print("NO DATA")

        time.sleep(SLEEP)

    # 4. Sort by freq_avg descending
    results.sort(key=lambda r: r["freq_avg"], reverse=True)

    # 5. Write CSV
    csv_path = Path("step2_scan_results.csv")
    fieldnames = [
        "symbol", "interval_h", "total_events", "qualifying",
        "freq_min", "freq_max", "freq_avg", "biggest_single_rate"
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n[+] CSV written to: {csv_path}")

    # 6. Print top 15
    print(f"\n{'=' * 60}")
    print(f"TOP 15 by avg 7-day qualifying frequency")
    print(f"{'=' * 60}")
    header = (
        f"{'Symbol':<16s} {'Int':>5s} {'Events':>7s} {'Qual':>6s} "
        f"{'Fmin':>5s} {'Fmax':>5s} {'Favg':>6s} {'Biggest':>10s}"
    )
    print(header)
    print("-" * len(header))
    for r in results[:15]:
        print(
            f"{r['symbol']:<16s} {r['interval_h']:>5.1f} {r['total_events']:>7d} "
            f"{r['qualifying']:>6d} {r['freq_min']:>5d} {r['freq_max']:>5d} "
            f"{r['freq_avg']:>6.1f} {r['biggest_single_rate'] * 100:>9.4f}%"
        )

    print(f"\n[+] Done. {len(results)} coins scanned, {len(results)} with data.")
    print(f"[+] Full results: {csv_path}")


if __name__ == "__main__":
    main()
