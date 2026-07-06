"""
Step 3: Order book depth test on top funding candidates.

Coins: COAIUSDT, LABUSDT, PIPPINUSDT, HUSDT, BEATUSDT
Per coin: pull top 10 levels both sides, sum top 5 in USDT, report smaller side + spread %.
"""

import json
import sys
import time

import requests

BASE_URL = "https://fapi.asterdex.com"

COINS = ["COAIUSDT", "LABUSDT", "PIPPINUSDT", "HUSDT", "BEATUSDT"]
SAMPLE_COIN = "COAIUSDT"


def fetch_orderbook(symbol: str, limit: int = 10) -> dict:
    r = requests.get(f"{BASE_URL}/fapi/v1/depth", params={"symbol": symbol, "limit": limit}, timeout=15)
    r.raise_for_status()
    return r.json()


def analyze_book(data: dict, top_n: int = 5) -> dict:
    """Sum top N levels on each side, return the smaller side in USDT + spread."""
    bids = [(float(price), float(qty)) for price, qty in data["bids"][:top_n]]
    asks = [(float(price), float(qty)) for price, qty in data["asks"][:top_n]]

    bid_usdt = sum(price * qty for price, qty in bids)
    ask_usdt = sum(price * qty for price, qty in asks)

    best_bid = bids[0][0] if bids else 0
    best_ask = asks[0][0] if asks else 0
    spread_pct = ((best_ask - best_bid) / best_bid * 100) if best_bid > 0 else 0

    return {
        "bid_usdt": bid_usdt,
        "ask_usdt": ask_usdt,
        "book_top_usdt": min(bid_usdt, ask_usdt),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": spread_pct,
        "bids": bids,
        "asks": asks,
    }


def main():
    print("=" * 60)
    print("STEP 3: Order Book Depth Test")
    print("=" * 60)

    # Print raw for first coin
    print(f"\n[*] Fetching raw order book for {SAMPLE_COIN}...")
    raw = fetch_orderbook(SAMPLE_COIN, limit=10)
    print(f"\n{'=' * 60}")
    print(f"RAW RESPONSE — {SAMPLE_COIN}")
    print(f"{'=' * 60}")
    print(f"Top 5 BIDS:")
    for i, (price, qty) in enumerate(raw["bids"][:5]):
        usdt = float(price) * float(qty)
        print(f"  [{i+1}] price={price:<14s} qty={qty:<14s} usdt={usdt:>12.2f}")
    print(f"Top 5 ASKS:")
    for i, (price, qty) in enumerate(raw["asks"][:5]):
        usdt = float(price) * float(qty)
        print(f"  [{i+1}] price={price:<14s} qty={qty:<14s} usdt={usdt:>12.2f}")

    # Scan all candidates
    print(f"\n{'=' * 60}")
    print(f"[*] Scanning {len(COINS)} candidates...")
    print(f"{'=' * 60}")

    results = []
    for symbol in COINS:
        data = fetch_orderbook(symbol, limit=10)
        info = analyze_book(data, top_n=5)
        results.append({"symbol": symbol, **info})
        print(f"  {symbol:<16s} bid={info['bid_usdt']:>12,.0f}  ask={info['ask_usdt']:>12,.0f}  smaller={info['book_top_usdt']:>12,.0f}  spread={info['spread_pct']:.4f}%")
        time.sleep(0.2)

    # Sort by book_top_usdt descending
    results.sort(key=lambda r: r["book_top_usdt"], reverse=True)

    print(f"\n{'=' * 60}")
    print(f"RESULTS (sorted by book_top_usdt, descending)")
    print(f"{'=' * 60}")
    header = f"{'Symbol':<16s} {'Bid5_USDT':>12s} {'Ask5_USDT':>12s} {'Book_USDT':>12s} {'Spread%':>8s}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['symbol']:<16s} {r['bid_usdt']:>12,.0f} {r['ask_usdt']:>12,.0f} {r['book_top_usdt']:>12,.0f} {r['spread_pct']:>7.4f}%")

    print(f"\n[+] Done. No pass/fail — set order size after checking leverage in UI.")


if __name__ == "__main__":
    main()
