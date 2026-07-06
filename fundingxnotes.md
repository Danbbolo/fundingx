# FundingX — Session Notes
Started: July 6, 2026

## Infrastructure
- **Azure VM**: 48.209.16.63 (Ubuntu 24.04, 2 vCPU, 4GB RAM)
- **SSH user**: azureuser
- **SSH key**: Desktop/arb_key.pem
- **Python**: 3.12.3 on Azure box
- **Local dev**: Windows, Python 3.11+, workspace at c:\Users\User\fundingx
- **GitHub**: https://github.com/Danbbolo/fundingx (branch: master)

## Strategy Summary
- DEX funding fee sniper on **Aster DEX** (asterdex.com) — Pro mode / orderbook perps ONLY
- API: `fapi.asterdex.com` (Binance-style endpoints)
- Capital: €500
- Enter minutes before funding settlement, collect funding, exit right after

## Pipeline Steps
1. **Fees → threshold** — Fetch Aster Pro taker fees, threshold = round-trip fee × 3, scaled by interval
2. **Scan all pairs** — Detect real funding interval per coin, pull full history, count qualifying spikes, rolling 7-day stats
3. **Book test** — Order book depth check on top candidates (€500 × leverage)
4. **Predictability check** — Live monitor T-10min vs settled rate, 10+ observations
5. **€50 manual live test** on best coin

## Workflow
- **Code locally** (Windows, VS Code, c:\Users\User\fundingx)
- **Run/deploy on Azure** (48.209.16.63, SSH via `ssh -i "C:\Users\User\Desktop\arb_key.pem" azureuser@48.209.16.63`)
- Write scripts locally → SCP/rsync to Azure → run there
- Always commit + push to GitHub after each step

## Working Rules
- Raw data first, never state unverified numbers
- Units explicit (API decimals: 0.0002 = 0.02%)
- Sample sizes with every claim
- Suspicious results → investigate, don't adjust
- One task per prompt, human-verified before next
- Always exclude Aster Simple/Degen modes

## Progress Checklist
- [x] Step 1: Fees → threshold ✅ (2026-07-06)
- [x] Step 2: Scan all pairs ✅ (2026-07-06)
- [x] Step 3: Book test on top candidates ✅ (2026-07-06)
- [x] Step A: cryptohftdata exploration ✅ (2026-07-06)
- [x] Step B/C: L2 book reconstruction at settlement T-5min ✅ (2026-07-06)
- [x] Task 1: Missing coins check ✅ (2026-07-06) — all 0 qualifying in 14d
- [x] Task 2: Entry timing analysis ✅ (2026-07-06) — T-5 worst, T-15/T-1 best
- [ ] Step 4: Predictability check (live monitor LABUSDT)
- [ ] Step 5: €50 manual live test

## Current Status (2026-07-06)
- **Only viable coin: LABUSDT** (123 qualifying in 14d, $4.7k median depth)
- **Best entry timing: T-15min or T-1min** (NOT T-5 — books collapse there)
- PIPPIN/COAI/BEAT/AIA/HOME: all dried up in last 14 days
- TAIKOUSDT: suspicious -2.0% cap hits
- HUSDT/BIRBUSDT: too thin or too few events
- Next: Step 4 predictability check → Step 5 €50 live test

## Key Findings
### Step 1 — Fee → Threshold (2026-07-06)
- Source: https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees.md
- USDT-Perpetual Contracts (Pro mode): Maker = 0%, Taker = 0.04%
- Round-trip taker = 2 × 0.0004 = 0.0008 (0.08%)
- **Threshold = 0.0024 (0.24%)**
- No interval scaling — fees are per-trade regardless of funding interval
- A funding rate must have |rate| >= 0.0024 to qualify

### Step 2 — Full Scan (2026-07-06)
- Scanned 500 USDT perpetuals on Aster Pro mode
- Raw data: step2_scan_results.csv
- **TOP 15 by avg 7-day qualifying frequency:**

| Symbol | Int | Events | Qual | Favg | Red flag? |
|--------|-----|--------|------|------|-----------|
| HOMEUSDT | 1h | 1089 | 155 | 24.0 | ⚠️ Only 1089 events, 14% qualify — investigate raw rates |
| TAIKOUSDT | 1h | 109 | 23 | 20.0 | ⚠️ Only 109 events — tiny sample, unreliable |
| COAIUSDT | 1h | 2000 | 181 | 15.3 | Check if rates repeat at same value |
| LABUSDT | 1h | 2000 | 191 | 14.6 | Check raw |
| PIPPINUSDT | 1h | 2000 | 157 | 12.3 | |
| HUSDT | 1h | 2000 | 84 | 7.1 | |
| BEATUSDT | 1h | 2000 | 93 | 6.1 | |
| BIRBUSDT | 1h | 2000 | 70 | 5.8 | |
| AIAUSDT | 1h | 2000 | 80 | 5.5 | |
| ARXUSDT | 1h | 322 | 10 | 5.2 | ⚠️ Only 322 events |
| FIDAUSDT | 1h | 1158 | 33 | 4.8 | |
| TNSRUSDT | 1h | 2000 | 51 | 4.3 | |
| ENJUSDT | 1h | 2000 | 51 | 4.2 | |
| REUSDT | 1h | 419 | 10 | 4.0 | ⚠️ Only 419 events |
| SLXUSDT | 1h | 821 | 32 | 4.0 | |

- All top coins are 1h interval
- BTC/ETH/SOL/DOGE = 0 qualifying (majors have tiny funding)
- 0.24% threshold filters out ~85% of all coins

### Step 3 — Book Test (2026-07-06)
Tested: COAIUSDT, LABUSDT, PIPPINUSDT, HUSDT, BEATUSDT

| Symbol | Book_USDT (smaller side) | Spread% | Notes |
|--------|-------------------------|---------|-------|
| PIPPINUSDT | 21,377 | 0.21% | Best depth |
| BEATUSDT | 2,578 | 0.09% | Tight spread |
| LABUSDT | 2,348 | 0.03% | Tightest spread |
| COAIUSDT | 1,880 | 0.48% | ⚠️ Wide spread, huge bid/ask imbalance |
| HUSDT | 811 | 0.14% | ⚠️ Too thin for €500 |

- Raw top 5 levels printed for COAIUSDT (verified)
- COAIUSDT: 21k bid vs 1.8k ask — massive imbalance, wide spread
- HUSDT: only 811 USDT depth — too thin
- No pass/fail yet — need leverage info from UI to set order size

### Step A — cryptohftdata.com Exploration (2026-07-06)
- **Aster order book history confirmed** — 538 symbols, incremental L2 data
- API: `api.cryptohftdata.com` (needs API key, saved on Azure ~/.env)
- **No snapshot-at-timestamp endpoint** — must download full hourly parquet files
- File format: `.parquet.zst`, columns: received_time(ns), event_time(ms), side, price, qty
- Each row = one price level update (incremental L2), ~352k rows/hour for BTCUSDT
- File sizes: LABUSDT 2MB/hr, others 49KB-500KB/hr
- **Smart subset needed**: only download hours with qualifying settlements

### Step B/C — L2 Book at Settlement T-5min (2026-07-06)
Source: cryptohftdata.com historical L2 order book data
Method: vectorized pandas groupby replay, top 5 levels each side, smaller side in USDT

**VERDICT TABLE (book depth at T-5min before qualifying settlements):**

| Symbol | Calm_Baseline | Worst_Case | Median | Best | Qualifying |
|--------|--------------|------------|--------|------|------------|
| **LABUSDT** | $5,615 | **$421** | $4,696 | $17,697 | 123 |
| TAIKOUSDT | $783 | $341 | $1,800 | $14,449 | 23 |
| BIRBUSDT | $1,798 | $1,498 | $3,488 | $3,488 | 2 |
| HUSDT | $1,179 | $290 | $382 | $382 | 2 |

**LABUSDT worst 10 settlements (thinnest books):**
| Time | Rate% | Book_USDT |
|------|-------|-----------|
| 2026-06-27 19:00 | -0.58% | $421 |
| 2026-06-27 16:00 | -0.48% | $507 |
| 2026-07-01 04:00 | -0.40% | $539 |
| 2026-06-29 11:00 | -0.62% | $599 |
| 2026-06-24 17:00 | -0.57% | $733 |

**TAIKOUSDT notes:**
- Rates hit -2.0% cap repeatedly — investigate if this is a data artifact
- Book varies wildly: $341 to $14,449

**Key takeaways:**
- 0 zero-book results — T-5min fix works (download prev hour + current hour)
- Book shrinks during hot settlements vs calm baseline
- LABUSDT: worst-case $421 means €500 at 1x leverage barely fits, at any leverage it's too thin
- HUSDT: $290 worst case — unusable
- BIRBUSDT: only 2 events — not enough data

### Task 1 — Missing Coins (2026-07-06)
PIPPINUSDT, COAIUSDT, BEATUSDT, AIAUSDT, HOMEUSDT: **all have 0 qualifying events in last 14 days.**
Data exists at cryptohftdata and Aster API, but these coins' funding rates dropped below 0.24% threshold recently.
Their high Step 2 averages were from older historical data. Not usable currently.

### Task 2 — LABUSDT Entry Timing (2026-07-06)
Book depth at 4 lead times before 123 qualifying settlements:

| Lead Time | Median | Worst | Best |
|-----------|--------|-------|------|
| T-30min | $5,058 | $351 | $10,668 |
| T-15min | $5,086 | $403 | $11,621 |
| **T-5min** | **$4,696** | **$421** | $17,697 |
| T-1min | $4,987 | $369 | $14,601 |

**5 thinnest T-5min events — all 4 moments:**

| Time | Rate | T-30 | T-15 | T-5 | T-1 |
|------|------|------|------|-----|-----|
| Jun 27 19:00 | -0.58% | $4,781 | $3,477 | **$421** | $3,940 |
| Jun 27 16:00 | -0.48% | $5,269 | $1,342 | **$507** | $5,289 |
| Jul 01 04:00 | -0.40% | $9,949 | $3,444 | **$539** | $7,289 |
| Jun 29 11:00 | -0.62% | $5,974 | $2,021 | **$599** | $4,523 |
| Jun 24 17:00 | -0.57% | $4,403 | $5,228 | **$733** | $505 |

**Key insight (since corrected):** Initial claim was T-5 collapse. **Selection bias check revealed: minimum depth is spread evenly across all 4 lead times (T-30: 27.6%, T-15: 27.6%, T-5: 23.6%, T-1: 21.1%). Timing doesn't matter — depth is just noisy.**

### Selection Bias Check (2026-07-06)
For each of 123 LABUSDT settlements, found which lead time had MINIMUM depth:
T-30: 34 (27.6%) | T-15: 34 (27.6%) | T-5: 29 (23.6%) | T-1: 26 (21.1%)
**Near-uniform distribution. No special T-5 collapse. Timing doesn't affect depth.**

### Step D — Backtest Simulation (2026-07-06)
Walked historical order books at T-1min entry / T+1min exit for 4 coins over 14 days.
Entry: market order walking top 20 levels. Exit: same. Slippage + fees + funding modeled.

**Worked example (LABUSDT 2026-06-24 12:00, rate -0.31%, SHORT):**
- Order: €500 × 10x = €5,000
- Bids: 16.661×202=$3,366 | 16.653×93=$1,549 | 16.652×207=$3,447 ← fills here
- Entry slip: 0.016% | Exit slip: 0.023%
- Funding: €15.60 | Fees: €4.00 | Slip: €1.93 | **Net: +€9.66**

**€500 base (LAB 10x, others 5x):**

| Coin | Order | Full | Partial | Skip | Net P&L | Per Trade |
|------|-------|------|---------|------|---------|-----------|
| LABUSDT | €5,000 | 123 | 0 | 0 | **+€1,761** | +€14.32 |
| TAIKOUSDT | €2,500 | 21 | 2 | 0 | **-€938** | -€40.76 |
| BIRBUSDT | €2,500 | 2 | 0 | 0 | -€33 | -€16.32 |
| HUSDT | €2,500 | 1 | 1 | 0 | -€109 | -€54.66 |
| **TOTAL** | | **147** | **3** | **0** | **+€682** | **+€4.55** |

**€250 base (half size):**

| Coin | Order | Net P&L | Per Trade |
|------|-------|---------|-----------|
| LABUSDT | €2,500 | **+€996** | +€8.10 |
| TAIKOUSDT | €1,250 | -€185 | -€8.04 |
| BIRBUSDT | €1,250 | -€4 | -€2.19 |
| HUSDT | €1,250 | -€18 | -€9.04 |
| **TOTAL** | | **+€789** | **+€5.26** |

**Key findings:**
- **LABUSDT is the only profitable coin** — all others bleed
- Smaller size (€250) earns MORE per trade (€5.26 vs €4.55) — less slippage
- TAIKOUSDT loses badly (-€40/trade) — the -2% cap rates + wide books kill it
- HUSDT/BIRBUSDT: too thin, slippage eats all the funding
- **Recommendation: LABUSDT only, €250 base (€2,500 notional), skip all other coins**

## Checkpoint Log
<!-- Add checkpoints as we progress -->
