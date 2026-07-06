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
- [ ] Step 1: Fees → threshold
- [ ] Step 2: Scan all pairs
- [ ] Step 3: Book test on top candidates
- [ ] Step 4: Predictability check
- [ ] Step 5: €50 manual live test

## Key Findings
<!-- Add findings as we go -->

## Checkpoint Log
<!-- Add checkpoints as we progress -->
