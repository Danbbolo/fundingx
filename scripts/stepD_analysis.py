"""
Post-hoc analysis of backtest v2 per-trade results.
Parses the log output, no re-run needed.
Check 1: Distribution per coin
Check 2: Price P&L shape
Check 3: Out-of-sample split (days 1-7 select, days 8-14 trade)
"""
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ============================================================
# Parse log file
# ============================================================

def parse_log(filepath):
    """Parse stepD_v2_output.log into structured per-trade data."""
    trades = []
    current_coin = None
    current_base = None
    current_leverage = None
    
    # Pattern for summary lines like "LABUSDT @ €500 base × 10x = €5,000"
    summary_re = re.compile(r'^(\w+USDT)\s+@\s+€(\d+)\s+base\s+×\s+(\d+)x')
    
    # Pattern for trade lines:
    # 2026-06-24T12:00:00.012000+00:00  LONG  -0.312   5,000.00     +26.95   15.5958    4.00     +36.72 full
    trade_re = re.compile(
        r'^\s+(\d{4}-\d{2}-\d{2}T[\d:.]+[+\-]\d{2}:\d{2})\s+'
        r'(LONG|SHORT)\s+'
        r'([-\d.]+)\s+'      # rate%
        r'([\d,.]+)\s+'      # filled
        r'([+\-][\d,.]+)\s+' # price_pnl
        r'([\d.]+)\s+'       # funding
        r'([\d.]+)\s+'       # fees
        r'([+\-][\d,.]+)\s+' # net
        r'(full|partial)'
    )
    
    with open(filepath) as f:
        for line in f:
            m = summary_re.match(line)
            if m:
                current_coin = m.group(1)
                current_base = int(m.group(2))
                current_leverage = int(m.group(3))
                continue
            
            m = trade_re.match(line)
            if m and current_coin:
                time_str = m.group(1)
                dt = datetime.fromisoformat(time_str)
                trades.append({
                    "coin": current_coin,
                    "base": current_base,
                    "leverage": current_leverage,
                    "time": dt,
                    "direction": m.group(2),
                    "rate_pct": float(m.group(3)),
                    "filled": float(m.group(4).replace(",", "")),
                    "price_pnl": float(m.group(5).replace(",", "").replace("+", "")),
                    "funding": float(m.group(6)),
                    "fees": float(m.group(7)),
                    "net": float(m.group(8).replace(",", "").replace("+", "")),
                    "status": m.group(9),
                })
    
    return trades


# ============================================================
# CHECK 1: Distribution
# ============================================================

def check_distribution(trades):
    print("=" * 80)
    print("CHECK 1: Distribution per coin")
    print("=" * 80)
    
    coins = defaultdict(list)
    for t in trades:
        coins[t["coin"]].append(t)
    
    print(f"\n{'Coin':<14s} {'N':>4s} {'Median':>9s} {'Worst':>9s} {'Best':>9s} {'WinRt':>6s} {'MaxLoss':>7s} {'Outlier%':>9s}")
    print("-" * 72)
    
    for coin in sorted(coins.keys()):
        trs = coins[coin]
        nets = sorted([t["net"] for t in trs])
        n = len(nets)
        median = nets[n // 2]
        worst = nets[0]
        best = nets[-1]
        wins = sum(1 for x in nets if x > 0)
        win_rate = wins / n * 100
        
        # Max losing streak
        max_streak = 0
        current_streak = 0
        for x in nets:
            if x < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        # Outlier dependency: what % of total comes from top 3 trades?
        total = sum(nets)
        top3 = sum(sorted(nets, reverse=True)[:3])
        outlier_pct = (top3 / total * 100) if total > 0 else 0
        
        print(f"{coin:<14s} {n:>4d} {median:>+9.2f} {worst:>+9.2f} {best:>+9.2f} {win_rate:>5.1f}% {max_streak:>7d} {outlier_pct:>8.1f}%")
    
    # Overall
    all_nets = sorted([t["net"] for t in trades])
    total = sum(all_nets)
    top5 = sum(sorted(all_nets, reverse=True)[:5])
    print(f"\n  Overall: {len(all_nets)} trades, total €{total:+,.2f}")
    print(f"  Top 5 trades = €{top5:+,.2f} ({top5/total*100:.1f}% of total)")
    print(f"  Bottom 5 trades = €{sum(all_nets[:5]):+,.2f}")


# ============================================================
# CHECK 2: Price P&L shape
# ============================================================

def check_price_pnl_shape(trades):
    print(f"\n{'=' * 80}")
    print("CHECK 2: Price P&L Distribution")
    print("=" * 80)
    
    price_pnls = [t["price_pnl"] for t in trades]
    price_pnls.sort()
    
    n = len(price_pnls)
    mean = sum(price_pnls) / n
    median = price_pnls[n // 2]
    
    print(f"\n  N:       {n}")
    print(f"  Mean:    €{mean:+,.2f}")
    print(f"  Median:  €{median:+,.2f}")
    print(f"  Min:     €{min(price_pnls):+,.2f}")
    print(f"  Max:     €{max(price_pnls):+,.2f}")
    print(f"  Std:     €{(sum((x - mean)**2 for x in price_pnls) / n) ** 0.5:,.2f}")
    
    # Histogram
    bins = [-500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500, 3000]
    print(f"\n  Histogram (price P&L in €):")
    print(f"  {'Range':>15s} {'Count':>6s} {'%':>6s} {'Bar'}")
    print(f"  {'-'*50}")
    
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        count = sum(1 for x in price_pnls if lo <= x < hi)
        pct = count / n * 100
        bar = "#" * int(pct / 2)
        label = f"€{lo} to €{hi}"
        print(f"  {label:>15s} {count:>6d} {pct:>5.1f}% {bar}")
    
    # Contribution analysis
    positive = [x for x in price_pnls if x > 0]
    negative = [x for x in price_pnls if x < 0]
    print(f"\n  Positive trades: {len(positive)} ({len(positive)/n*100:.1f}%) = €{sum(positive):+,.2f}")
    print(f"  Negative trades: {len(negative)} ({len(negative)/n*100:.1f}%) = €{sum(negative):+,.2f}")
    print(f"  Zero:            {n - len(positive) - len(negative)}")
    
    # Top 5 and bottom 5
    by_pnl = sorted(trades, key=lambda t: t["price_pnl"], reverse=True)
    print(f"\n  Top 5 price P&L:")
    for t in by_pnl[:5]:
        print(f"    {t['coin']:<14s} {t['time'].strftime('%m-%d %H:%M')} {t['direction']:>5s} €{t['price_pnl']:+,.2f}")
    print(f"  Bottom 5 price P&L:")
    for t in by_pnl[-5:]:
        print(f"    {t['coin']:<14s} {t['time'].strftime('%m-%d %H:%M')} {t['direction']:>5s} €{t['price_pnl']:+,.2f}")


# ============================================================
# CHECK 3: Out-of-sample split
# ============================================================

def check_oos_split(trades):
    print(f"\n{'=' * 80}")
    print("CHECK 3: Out-of-Sample Split")
    print("  Days 1-7: select qualifying coins")
    print("  Days 8-14: compute P&L on those coins ONLY")
    print("=" * 80)
    
    if not trades:
        print("  No trades"); return
    
    # Find the window boundaries
    min_date = min(t["time"] for t in trades).date()
    max_date = max(t["time"] for t in trades).date()
    total_days = (max_date - min_date).days + 1
    split_date = min_date + timedelta(days=7)
    
    print(f"\n  Window: {min_date} to {max_date} ({total_days} days)")
    print(f"  Split at: {split_date}")
    
    # Days 1-7: which coins qualify (have any qualifying settlements)?
    train_trades = [t for t in trades if t["time"].date() < split_date]
    test_trades = [t for t in trades if t["time"].date() >= split_date]
    
    train_coins = set(t["coin"] for t in train_trades)
    test_coins = set(t["coin"] for t in test_trades)
    
    print(f"\n  Days 1-7: {len(train_trades)} trades, coins: {sorted(train_coins)}")
    print(f"  Days 8-14: {len(test_trades)} trades, coins: {sorted(test_coins)}")
    
    # OOS: only trades on days 8-14 for coins that qualified in days 1-7
    oos_trades = [t for t in test_trades if t["coin"] in train_coins]
    oos_skipped = [t for t in test_trades if t["coin"] not in train_coins]
    
    print(f"\n  OOS trades (days 8-14, coins from days 1-7): {len(oos_trades)}")
    if oos_skipped:
        skipped_coins = set(t["coin"] for t in oos_skipped)
        print(f"  Skipped (new coins in days 8-14 only): {sorted(skipped_coins)} ({len(oos_skipped)} trades)")
    
    # OOS results
    oos_by_coin = defaultdict(list)
    for t in oos_trades:
        oos_by_coin[t["coin"]].append(t)
    
    print(f"\n  {'Coin':<14s} {'Trades':>6s} {'Funding':>9s} {'Price':>9s} {'Fees':>7s} {'Slip':>9s} {'Net':>9s}")
    print(f"  {'-'*65}")
    
    total_funding = total_price = total_fees = total_slip = total_net = 0
    
    for coin in sorted(oos_by_coin.keys()):
        trs = oos_by_coin[coin]
        funding = sum(t["funding"] for t in trs)
        price = sum(t["price_pnl"] for t in trs)
        fees = sum(t["fees"] for t in trs)
        net = sum(t["net"] for t in trs)
        slip = funding - fees + price - net  # reconstruct
        
        total_funding += funding
        total_price += price
        total_fees += fees
        total_net += net
        
        print(f"  {coin:<14s} {len(trs):>6d} {funding:>+9.2f} {price:>+9.2f} {fees:>7.2f} {slip:>9.2f} {net:>+9.2f}")
    
    print(f"  {'-'*65}")
    print(f"  {'TOTAL':<14s} {len(oos_trades):>6d} {total_funding:>+9.2f} {total_price:>+9.2f} {total_fees:>7.2f} {'':>9s} {total_net:>+9.2f}")
    
    # Compare IS vs OOS
    is_total = sum(t["net"] for t in train_trades)
    print(f"\n  In-sample (days 1-7) net:  €{is_total:+,.2f}")
    print(f"  Out-of-sample (days 8-14) net: €{total_net:+,.2f}")
    if is_total != 0:
        print(f"  OOS/IS ratio: {total_net / is_total:.2f}x")


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = "/home/azureuser/stepD_v2_output.log"
    
    print(f"Parsing: {filepath}")
    trades = parse_log(filepath)
    print(f"Parsed {len(trades)} trades")
    
    if not trades:
        print("No trades found. Check file path."); return
    
    check_distribution(trades)
    check_price_pnl_shape(trades)
    check_oos_split(trades)


if __name__ == "__main__":
    main()
