"""
Step B-1: Get qualifying settlements for all target coins.
For each qualifying settlement, compute the cryptohftdata file path needed.
"""
import requests
import time
from datetime import datetime, timezone, timedelta

BASE_URL = "https://fapi.asterdex.com"
THRESHOLD = 0.0024
LOOKBACK_DAYS = 14

COINS = ["HOMEUSDT", "TAIKOUSDT", "COAIUSDT", "LABUSDT", "PIPPINUSDT", "HUSDT", "BEATUSDT", "BIRBUSDT", "AIAUSDT"]

def fetch_funding_history(symbol):
    all_entries = []
    end_time = None
    while True:
        params = {"symbol": symbol, "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        try:
            r = requests.get(f"{BASE_URL}/fapi/v1/fundingRate", params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except:
            break
        if not data:
            break
        all_entries.extend(data)
        if len(data) < 1000:
            break
        end_time = data[0]["fundingTime"] - 1
        time.sleep(0.1)
    return all_entries

print("=" * 70)
print("Step B-1: Qualifying Settlements (last 14 days)")
print("=" * 70)

cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

all_files_needed = {}  # symbol -> set of file paths

for symbol in COINS:
    entries = fetch_funding_history(symbol)
    if not entries:
        print(f"\n{symbol}: NO DATA")
        continue

    # Filter to last 14 days
    recent = [e for e in entries if e["fundingTime"] >= cutoff_ms]
    
    # Filter to qualifying
    qualifying = [e for e in recent if abs(float(e["fundingRate"])) >= THRESHOLD]
    
    # Build file paths: aster_futures/YYYY-MM-DD/HH/SYMBOL_orderbook.parquet.zst
    file_paths = set()
    for e in qualifying:
        ts = datetime.fromtimestamp(e["fundingTime"] / 1000, tz=timezone.utc)
        path = f"aster_futures/{ts.strftime('%Y-%m-%d')}/{ts.strftime('%H')}/{symbol}_orderbook.parquet.zst"
        file_paths.add(path)
    
    all_files_needed[symbol] = file_paths
    
    print(f"\n{symbol}: {len(recent)} total in 14d, {len(qualifying)} qualifying")
    if qualifying:
        rates = [float(e["fundingRate"]) for e in qualifying]
        print(f"  Rate range: {min(rates)*100:.4f}% to {max(rates)*100:.4f}%")
        print(f"  Unique hours to download: {len(file_paths)}")
        # Print first few
        for path in sorted(file_paths)[:3]:
            print(f"    {path}")
        if len(file_paths) > 3:
            print(f"    ... and {len(file_paths)-3} more")

# Summary
total_files = sum(len(paths) for paths in all_files_needed.values())
print(f"\n{'=' * 70}")
print(f"TOTAL: {total_files} unique hourly files to download")
print(f"{'=' * 70}")

# Output the file list for the downloader
with open("stepB_file_list.txt", "w") as f:
    for symbol, paths in all_files_needed.items():
        for path in sorted(paths):
            f.write(path + "\n")
print(f"\nFile list saved to stepB_file_list.txt")
