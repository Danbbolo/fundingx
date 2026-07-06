# Funding Sniper — Fresh Start
Updated: July 6, 2026

## The strategy
Crypto perpetuals pay "funding" between longs and shorts at fixed settlement times (every 1h, 4h, or 8h depending on the coin). Some coins regularly hit funding rates big enough to beat trading fees. The plan: enter a position minutes before settlement, be holding at the settlement timestamp, collect the payment, exit right after. Small exposure window, statistical edge over many repeats. Capital: €500.

## Target venue
Aster DEX (asterdex.com) — Pro mode / orderbook perpetuals ONLY. Aster's Simple and Degen modes use pool-based mechanics with different fees and no comparable funding — always exclude them. API: fapi.asterdex.com (Binance-style endpoints).

## The pipeline — one step per task, in order

1. **Fees → threshold.** Fetch Aster Pro mode's real fee schedule from their docs. Threshold = round-trip taker fee × 3, on an 8h basis. Scale per coin: threshold × (coin's interval / 8). Print the derivation.

2. **Scan all pairs.** Per coin: detect the real funding interval from history data (mode of time gaps — never assume 1h or 8h; they vary per coin). Pull full available funding history. Count qualifying events (|rate| >= that coin's scaled threshold). Report frequency as rolling 7-day windows: min / max / average. Never a single-window number.

3. **Book test on the top candidates.** Order size = €500 × the coin's leverage (check leverage manually in the UI — the API doesn't reliably expose it; leave a column blank for it). Pull the order book, sum the top ~5 levels. Book must hold >= the order size, else the coin can't be entered at size. Log the numbers.

4. **Predictability check on the finalists.** Live monitor: poll the coin's live funding rate (premiumIndex endpoint) from T-10min to each settlement, then compare against the actually settled rate. Question: is the settlement value visible in advance, and how early does it stabilize? Run across enough settlements to judge (10+), and judge only on qualifying-magnitude settlements — near-zero duds are noise.

5. **€50 manual live test** on the best coin before any engine gets built.

## Working rules — non-negotiable
- Never state a number you didn't fetch raw in this session. Print the raw API response before using any value.
- Units explicit at every conversion. API rates are usually decimals: 0.0002 = 0.02%. Percent/decimal confusion is the most likely bug in this domain.
- Zero, negative, or "not found" are valid results. Never adjust a calculation until an implausible-looking result becomes plausible — investigate it instead.
- State the sample size with every statistical claim. One week of data confirms nothing.
- One task per prompt. Each output gets human-verified before the next task.
- If a result looks too good (a coin qualifying on ~100% of settlements, a huge rate that repeats at the exact same value), treat it as a bug or a data artifact until proven otherwise with raw data.
