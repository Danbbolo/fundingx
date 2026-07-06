"""Quick parser: extract scan results from step2_output.log and write CSV + top 15."""
import csv
import re
import sys
from pathlib import Path

log_path = Path("step2_output.log")
if not log_path.exists():
    print("step2_output.log not found"); sys.exit(1)

pattern = re.compile(
    r"\[\s*(\d+)/500\]\s+(\S+)\s+int=(\S+?)h\s+events=\s*(\d+)\s+qual=\s*(\d+)\s+avg=(\S+)"
)

results = []
with open(log_path) as f:
    for line in f:
        m = pattern.search(line)
        if m:
            results.append({
                "symbol": m.group(2),
                "interval_h": float(m.group(3)),
                "total_events": int(m.group(4)),
                "qualifying": int(m.group(5)),
                "freq_min": 0,
                "freq_max": 0,
                "freq_avg": float(m.group(6)),
                "biggest_single_rate": 0,
            })

results.sort(key=lambda r: r["freq_avg"], reverse=True)

csv_path = Path("step2_scan_results.csv")
fieldnames = ["symbol", "interval_h", "total_events", "qualifying", "freq_min", "freq_max", "freq_avg", "biggest_single_rate"]
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

print(f"Wrote {len(results)} rows to {csv_path}")
print()
print(f"TOP 15 by avg 7-day qualifying frequency")
print(f"{'Symbol':<20s} {'Int':>5s} {'Events':>7s} {'Qual':>6s} {'Favg':>6s}")
print("-" * 46)
for r in results[:15]:
    print(f"{r['symbol']:<20s} {r['interval_h']:>5.1f} {r['total_events']:>7d} {r['qualifying']:>6d} {r['freq_avg']:>6.1f}")
