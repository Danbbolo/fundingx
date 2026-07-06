"""
Post-hoc analysis v2: reads from backtest_v3_trades.json (€500 run only, no doubling).
Check 1: Distribution per coin
Check 2: Price P&L shape
Check 3: Out-of-sample split (days 1-7 select → days 8-14 trade)
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta


def load_trades(filepath):
    with open(filepath) as f:
        trades = json.load(f)
    # Filter to filled trades only
    filled = [t for t in trades if t["filled"] > 0]
    # Parse times
    for t in filled:
        t["time_dt"] = datetime.fromisoformat(t["time"])
    filled.sort(key=lambda t: t["time_dt"])
    return filled


def check_distribution(trades):
    print("=" * 80)
    print("CHECK 1: Distribution per coin (€500 run, deduplicated)")
    print("=" * 80)

    coins = defaultdict(list)
    for t in trades:
        coins[t["coin"]].append(t)

    expected = {"LABUSDT": 123, "TAIKOUSDT": 23, "BIRBUSDT": 2, "HUSDT": 2}

    print(f"\n  {'Coin':<14s} {'N':>4s} {'Exp':>4s} {'Match':>5s} {'Median':>9s} {'Worst':>9s} {'Best':>9s} {'Win%':>6s} {'MaxLs':>6s} {'Outl%':>7s}")
    print(f"  {'-' * 75}")

    for coin in sorted(coins.keys()):
        trs = coins[coin]
        nets = sorted([t["net"] for t in trs])
        n = len(nets)
        exp = expected.get(coin, "?")
        match = "✓" if n == exp else f"✗ (got {n})"

        median = nets[n // 2]
        worst = nets[0]
        best = nets[-1]
        wins = sum(1 for x in nets if x > 0)
        win_rate = wins / n * 100

        # Max losing streak
        max_streak = 0
        streak = 0
        for t in sorted(trs, key=lambda x: x["time_dt"]):
            if t["net"] < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        # Outlier dependency: top 3 as % of total
        total = sum(nets)
        top3 = sum(sorted(nets, reverse=True)[:3])
        outlier_pct = (top3 / total * 100) if total > 0 else 0

        print(f"  {coin:<14s} {n:>4d} {str(exp):>4s} {match:>5s} {median:>+9.2f} {worst:>+9.2f} {best:>+9.2f} {win_rate:>5.1f}% {max_streak:>6d} {outlier_pct:>6.1f}%")

    # Overall
    all_nets = sorted([t["net"] for t in trades])
    total = sum(all_nets)
    top5 = sum(sorted(all_nets, reverse=True)[:5])
    bot5 = sum(all_nets[:5])
    print(f"\n  Total: {len(all_nets)} trades, net €{total:+,.2f}")
    print(f"  Top 5 trades = €{top5:+,.2f} ({top5/total*100:.1f}% of total)")
    print(f"  Bottom 5 trades = €{bot5:+,.2f}")


def check_price_pnl_shape(trades):
    print(f"\n{'=' * 80}")
    print("CHECK 2: Price P&L Distribution")
    print("=" * 80)

    pnls = [t["price_pnl"] for t in trades]
    pnls.sort()
    n = len(pnls)
    mean = sum(pnls) / n
    median = pnls[n // 2]
    std = (sum((x - mean) ** 2 for x in pnls) / n) ** 0.5

    print(f"\n  N: {n}  Mean: €{mean:+,.2f}  Median: €{median:+,.2f}  Std: €{std:,.2f}")
    print(f"  Min: €{min(pnls):+,.2f}  Max: €{max(pnls):+,.2f}")

    # Histogram
    bins = [-500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500, 3000]
    print(f"\n  {'Range':>15s} {'N':>5s} {'%':>6s}  Bar")
    print(f"  {'-' * 50}")
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        count = sum(1 for x in pnls if lo <= x < hi)
        pct = count / n * 100
        bar = "█" * int(pct / 2)
        print(f"  {'€%d to €%d' % (lo, hi):>15s} {count:>5d} {pct:>5.1f}%  {bar}")

    pos = [x for x in pnls if x > 0]
    neg = [x for x in pnls if x < 0]
    print(f"\n  Positive: {len(pos)} ({len(pos)/n*100:.1f}%) = €{sum(pos):+,.2f}")
    print(f"  Negative: {len(neg)} ({len(neg)/n*100:.1f}%) = €{sum(neg):+,.2f}")

    by_pnl = sorted(trades, key=lambda t: t["price_pnl"], reverse=True)
    print(f"\n  Top 5 price P&L:")
    for t in by_pnl[:5]:
        print(f"    {t['coin']:<14s} {t['time_dt'].strftime('%m-%d %H:%M')} {t['direction']:>5s} €{t['price_pnl']:+,.2f}")
    print(f"  Bottom 5 price P&L:")
    for t in by_pnl[-5:]:
        print(f"    {t['coin']:<14s} {t['time_dt'].strftime('%m-%d %H:%M')} {t['direction']:>5s} €{t['price_pnl']:+,.2f}")


def check_oos_split(trades):
    print(f"\n{'=' * 80}")
    print("CHECK 3: Out-of-Sample Split (days 1-7 select → days 8-14 trade)")
    print("=" * 80)

    min_date = min(t["time_dt"] for t in trades).date()
    max_date = max(t["time_dt"] for t in trades).date()
    total_days = (max_date - min_date).days + 1
    split_date = min_date + timedelta(days=7)

    print(f"\n  Window: {min_date} to {max_date} ({total_days} days)")
    print(f"  Split: {split_date}")

    train = [t for t in trades if t["time_dt"].date() < split_date]
    test = [t for t in trades if t["time_dt"].date() >= split_date]

    train_coins = set(t["coin"] for t in train)
    test_coins = set(t["coin"] for t in test)

    print(f"\n  Days 1-7: {len(train)} trades, coins: {sorted(train_coins)}")
    print(f"  Days 8-14: {len(test)} trades, coins: {sorted(test_coins)}")

    # OOS: only test trades for coins that appeared in train
    oos = [t for t in test if t["coin"] in train_coins]
    skipped_coins = test_coins - train_coins
    skipped_trades = [t for t in test if t["coin"] not in train_coins]

    print(f"\n  OOS trades: {len(oos)}")
    if skipped_coins:
        print(f"  Skipped coins (not in days 1-7): {sorted(skipped_coins)} ({len(skipped_trades)} trades)")

    oos_by_coin = defaultdict(list)
    for t in oos:
        oos_by_coin[t["coin"]].append(t)

    print(f"\n  {'Coin':<14s} {'N':>4s} {'Funding':>9s} {'Price':>9s} {'Fees':>7s} {'Net':>9s}")
    print(f"  {'-' * 55}")

    t_fund = t_price = t_fees = t_net = 0
    for coin in sorted(oos_by_coin.keys()):
        trs = oos_by_coin[coin]
        fund = sum(t["funding"] for t in trs)
        price = sum(t["price_pnl"] for t in trs)
        fees = sum(t["fees"] for t in trs)
        net = sum(t["net"] for t in trs)
        t_fund += fund; t_price += price; t_fees += fees; t_net += net
        print(f"  {coin:<14s} {len(trs):>4d} {fund:>+9.2f} {price:>+9.2f} {fees:>7.2f} {net:>+9.2f}")

    print(f"  {'-' * 55}")
    print(f"  {'OOS TOTAL':<14s} {len(oos):>4d} {t_fund:>+9.2f} {t_price:>+9.2f} {t_fees:>7.2f} {t_net:>+9.2f}")

    is_net = sum(t["net"] for t in train)
    print(f"\n  In-sample net:  €{is_net:+,.2f}")
    print(f"  OOS net:        €{t_net:+,.2f}")
    if is_net != 0:
        print(f"  OOS/IS ratio:   {t_net / is_net:.2f}x")


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else "backtest_v3_trades.json"
    trades = load_trades(filepath)
    print(f"Loaded {len(trades)} filled trades from {filepath}")

    check_distribution(trades)
    check_price_pnl_shape(trades)
    check_oos_split(trades)


if __name__ == "__main__":
    main()
