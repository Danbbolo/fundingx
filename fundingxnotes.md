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
- [ ] Step 2: Scan all pairs
- [ ] Step 3: Book test on top candidates
- [ ] Step 4: Predictability check
- [ ] Step 5: €50 manual live test

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

## Checkpoint Log
<!-- Add checkpoints as we progress -->
