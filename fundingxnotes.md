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
### Direction Fix + Price P&L — Corrected Backtest v2 (2026-07-06)
Source: Aster docs — "Negative funding rate: short traders pay long traders."
**FIX: negative rate → LONG (we receive), positive rate → SHORT (we receive)**
Previous backtest had direction backwards!

**Worked example (LABUSDT Jun 24 12:00, rate -0.31%, LONG):**
- Order: €500 × 10x = €5,000
- Buy asks: 16.676×202=$3,369 | 16.678×29=$484 | 16.685×202=$3,370 ← fills
- Entry: 16.678 × 299.8 base = €5,000 (slip 0.014%)
- Exit:  16.768 × 298.2 base = €5,000 (slip 0.023%)
- **Price P&L: +€26.95** (price moved up, we profited as long)
- Funding: €15.60 | Fees: €4.00 | Slip: €1.83 | **Net: +€36.72**

**CORRECTED MAIN COINS (€500 base):**

| Coin | Order | Net P&L | Funding | Price P&L | Per Trade |
|------|-------|---------|---------|-----------|-----------|
| **LABUSDT** | €5,000 | **+€3,991** | +€3,017 | +€2,107 | +€32.45 |
| **TAIKOUSDT** | €2,500 | **+€2,095** | +€649 | +€2,659 | +€91.07 |
| BIRBUSDT | €2,500 | -€96 | +€13 | -€66 | -€47.97 |
| HUSDT | €2,500 | -€110 | +€16 | -€28 | -€55.14 |
| **TOTAL** | | **+€5,880** | **+€3,694** | **+€4,672** | **+€39.20** |

**CORRECTED LEFTOVER COINS (€500 base):**

| Coin | Order | Qual | Funding | Price P&L | Net |
|------|-------|------|---------|-----------|-----|
| **GUAUSDT** | €2,500 | 15 | +€539 | +€753 | **+€971** |
| SLXUSDT | €2,500 | 27 | +€279 | -€46 | -€80 |
| ZKPUSDT | €2,500 | 6 | +€49 | -€84 | -€149 |
| REUSDT | €2,500 | 5 | +€35 | -€25 | -€32 |

**COMBINED GRAND TOTAL (€500 base, all 8 coins, 203 trades):**
- **NET: +€6,589** over 14 days
- Funding: +€4,596 | Price P&L: +€5,269
- Funding and price P&L BOTH contribute roughly equally

**Key findings from corrected backtest:**
- TAIKOUSDT flips from -€938 to +€2,095 with correct direction!
- LABUSDT still the best (consistent), TAIKOUSDT volatile but profitable
- **GUAUSDT is a new star**: +€971 in 15 trades, consistent funding + price
- Price P&L is ~58% of total profit — this isn't just a funding play, price moves matter
- Smaller size still better per-trade (less slippage)
- **Recommended coins: LABUSDT, TAIKOUSDT, GUAUSDT**

### Backtest v2 Post-Hoc Analysis (2026-07-06)

**Check 1 — Distribution:**
| Coin | N | Median | Worst | Best | Win% | MaxLoseStreak | OutlierDep% |
|------|---|--------|-------|------|------|---------------|-------------|
| LABUSDT | 246 | +€12.71 | -€314 | +€447 | 64.2% | 88 | 17.9% |
| TAIKOUSDT | 46 | -€12.91 | -€382 | +€2,814 | 30.4% | 32 | 145.7% |
| HUSDT | 4 | -€5.87 | -€55 | +€14 | 25% | 3 | — |
| BIRBUSDT | 4 | -€17.02 | -€62 | -€15 | 0% | 4 | — |

- Top 5 trades = 66.2% of total profit → **heavily outlier-dependent**
- TAIKOUSDT: 145.7% outlier dependency — one +€2,804 trade carries everything
- LABUSDT: 88-trade losing streak in a row — psychologically brutal
- Win rate: LABUSDT 64%, TAIKOUSDT 30% — TAIKOUSDT is a lottery ticket

**Check 2 — Price P&L shape:**
- Mean: +€24.85 | Median: -€0.86 | Std: €210
- 48.7% positive, 51.3% negative — nearly coin-flip
- NOT consistent small gains — it's fat-tailed: a few huge spikes (+€2,804, +€1,407) carry everything
- Top 5 price P&L trades are all TAIKOUSDT on Jul 1-2 (big price move)
- **Price P&L is speculative, not mean-reversion**

**Check 3 — Out-of-sample (days 1-7 select, days 8-14 trade):**
- IS (days 1-7): +€3,979 | OOS (days 8-14): +€2,122 | OOS/IS = 0.53x
- Only LABUSDT survived the OOS filter (HUSDT qualified days 1-7 but had 0 trades days 8-14)
- TAIKOUSDT and GUAUSDT only appeared in days 8-14 → would be MISSED in real life
- OOS still profitable but 47% less than IS → some overfitting present
- **LABUSDT is the only robust coin** — survives the OOS split

### CORRECTED Post-Hoc Analysis v2 (2026-07-06) — €500 run only, deduplicated
**Check 1 — Distribution (trade counts verified: LAB=123, TAIKO=23, BIRB=2, H=2):**

| Coin | N | Median | Worst | Best | Win% | MaxLoseStreak | OutlierDep% |
|------|---|--------|-------|------|------|---------------|-------------|
| LABUSDT | 123 | +€17.95 | -€314 | +€447 | 63.4% | 5 | 27.9% |
| TAIKOUSDT | 23 | -€35.64 | -€382 | +€2,814 | 26.1% | 5 | **197.9%** |
| BIRBUSDT | 2 | -€34.43 | -€62 | -€34 | 0% | 2 | — |
| HUSDT | 2 | -€54.93 | -€55 | -€55 | 0% | 2 | — |

- Top 5 trades = **86.3%** of total profit — extremely outlier-dependent
- TAIKOUSDT: 197.9% outlier dependency — one +€2,804 trade carries everything
- LABUSDT: 5-trade max losing streak (not 88 — that was the doubling bug)
- **LABUSDT is the only coin worth trading** — consistent median, reasonable win rate

**Check 2 — Price P&L shape:**
- Mean: +€31.14 | Median: -€3.45 | Std: €266
- 48% positive, 52% negative — near coin-flip
- NOT mean reversion — fat-tailed, a few huge spikes carry everything
- TAIKOUSDT Jul 1-2 price spike (+€2,804, +€1,147) dominates
- **Price P&L is speculative noise, funding is the real alpha**

**Check 3 — OOS split (days 1-7 select → days 8-14 trade):**
- IS: +€2,550 | OOS: +€1,331 | OOS/IS = 0.52x
- Only LABUSDT survived OOS filter (TAIKOUSDT/BIRBUSDT appeared later)
- OOS still profitable but 48% decay
- **LABUSDT is the only robust, OOS-surviving coin**

### Exit Timing Test: T+1min vs T+10s (2026-07-06)
**Result: IDENTICAL.** Every metric matches exactly — €0 delta across all 123 trades.

**Data granularity:** L2 updates arrive at sub-millisecond resolution. T+10s exit gap: median -35ms, 100% within ±1s of target. No granularity issue.

**Why identical?** The price P&L comes from price movement between settlements (hours), not from seconds after exit. LABUSDT's price at T+10s ≈ price at T+1min — the market doesn't move in that window. Exit timing is irrelevant for this strategy.

**Implication:** No need to rush exits. T+1min is fine. Focus risk management on position sizing and coin selection, not exit timing.
### EXIT TIMING FIX (2026-07-06) — Previous comparison had cache eviction bug
The first comparison showed identical results because `_MAX_CACHE = 12` evicted 137 of 149 files.
Fixed version with all 149 files loaded shows **DRAMATICALLY different results:**

| Metric | T+1min | T+10s | Delta |
|--------|--------|-------|-------|
| Total net | **-€3,288** | **-€2,112** | +€1,176 |
| Funding | +€3,017 | +€3,017 | €0 |
| **Price P&L** | **-€5,152** | **-€3,911** | **+€1,241** |
| Avg exit slip | 0.073% | 0.084% | +0.01% |
| Win% | 23.6% | 23.6% | 0% |

### KLINE VERIFICATION (2026-07-06) — Independent proof via Aster's own candles
Source: `fapi.asterdex.com/fapi/v1/klines` (1m candles). NOT cryptohftdata.

**10 specific settlements:**
| Settlement | Rate% | T-1min | T+1min | Dir |
|------------|-------|--------|--------|-----|
| Jun 24 12:00 | -0.31 | 16.571 | 16.662 | UP |
| Jun 24 16:00 | -1.06 | 18.954 | 18.708 | DOWN |
| Jun 26 08:00 | -0.30 | 18.018 | 18.006 | DOWN |
| Jun 27 17:00 | -0.67 | 15.738 | 15.508 | DOWN |
| Jun 28 01:00 | -0.35 | 17.061 | 17.073 | UP |
| Jun 29 09:00 | -0.40 | 14.801 | 14.806 | UP |
| Jun 30 08:00 | -0.85 | 12.977 | 12.951 | DOWN |
| Jul 02 21:00 | -0.71 | 10.662 | 10.674 | UP |
| Jul 03 02:00 | -1.10 | 10.840 | 10.655 | DOWN |
| Jul 03 11:00 | -0.25 | 7.302 | 7.260 | DOWN |

**All 123 settlements:**
- Price UP at T+1min: **38 (30.9%)**
- Price DOWN at T+1min: **85 (69.1%)**
- Avg change UP: +0.65% | Avg change DOWN: -0.78%

**The kill shot:**
- Backtest v3 claimed: 63.4% win rate ← **WRONG** (cache bug)
- Kline reality: 30.9% UP rate ← **INDEPENDENTLY CONFIRMED**
- Exit comparison v2: -€3,288 net ← **CORRECT**

**Final conclusion: LABUSDT price drops 69% of the time after settlement. We go LONG (negative rate = longs receive), collecting funding but bleeding on price. The v3 backtest was fabricated by cache eviction. Strategy is net negative.**

### FULL-HISTORY DRIFT vs FUNDING (2026-07-06) — 191 settlements, 262 days, Aster klines only
Source: `fapi.asterdex.com/fapi/v1/klines` (1m candles). NO cryptohftdata.

**(A) Overall:**
| Metric | Value |
|--------|-------|
| Settlements | 191 |
| Funding total | +€5,445 |
| **Price P&L total** | **-€7,860** |
| **NET** | **-€2,414** |
| Per settlement | -€12.64 |
| Price UP after | 28 (14.7%) |
| Price DOWN after | 163 (85.3%) |
| Avg drift UP | +0.62% |
| Avg drift DOWN | -1.07% |

**(B) By regime (weekly price change):**
| Regime | N | Funding | Price P&L | Net | Per Trade |
|--------|---|---------|-----------|-----|-----------|
| Uptrend | 136 | +€4,257 | -€6,021 | -€1,764 | -€12.97 |
| Downtrend | 55 | +€1,188 | -€1,839 | -€651 | -€11.83 |
| Flat | 0 | — | — | — | — |

**No regime works.** Uptrend, downtrend — both lose ~€12-13 per trade. Price drops 85% of the time after settlement regardless of weekly trend. Funding (+€5,445) consistently fails to cover price drift (-€7,860).

**Weekly breakdown:**
| Week | Regime | N | Funding | Price | Net |
|------|--------|---|---------|-------|-----|
| W21 | uptrend | 2 | +€29 | +€25 | +€54 |
| W22 | uptrend | 66 | +€2,400 | -€4,048 | -€1,648 |
| W25 | downtrend | 55 | +€1,188 | -€1,839 | -€651 |
| W26 | uptrend | 68 | +€1,829 | -€1,998 | -€169 |

**Final verdict: The funding sniper strategy as designed does not work for LABUSDT across any regime, any time period, any exit timing. The post-settlement price drift is structural, not cyclical.**

**CRITICAL: Both versions LOSE MONEY.** The v3 backtest (+€3,991) was wrong — cache eviction bug.
- Price moves AGAINST the position after settlement (LABUSDT is always LONG, price drops)
- Funding (+€3,017) cannot overcome price loss (-€5,152 at T+1min, -€3,911 at T+10s)
- **Shorter exit (T+10s) loses €1,241 less** — less exposure to adverse price move
- Exit slippage slightly worse at T+10s (+0.01%) but price benefit far outweighs it

**Implication: Strategy is broken for LABUSDT.** The funding edge doesn't compensate for the post-settlement price drift. Need to either:
1. Find coins where funding consistently exceeds price drift
2. Hedge the price risk (delta-neutral)
3. Accept this strategy doesn't work as-is## Checkpoint Log
<!-- Add checkpoints as we progress -->
