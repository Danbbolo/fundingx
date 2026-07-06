"""Step A continued: explore with correct exchange name and check auth requirements."""
import json
import requests

BASE = "https://api.cryptohftdata.com"

# Try with aster_futures
print("[*] Checking /symbols with exchange='aster_futures'...")
for dtype in ["orderbook", "trades", "ticker", "mark_price"]:
    r = requests.get(f"{BASE}/symbols", params={"exchange": "aster_futures", "data_type": dtype})
    print(f"  {dtype:<20s}: HTTP {r.status_code}", end="")
    if r.ok:
        data = r.json()
        symbols = data.get("symbols", [])
        count = data.get("count", 0)
        print(f"  count={count}", end="")
        if symbols:
            print(f"  (first 10: {symbols[:10]})", end="")
        print()
    else:
        print(f"  body: {r.text[:200]}")

# Check if symbols endpoint needs auth
print("\n[*] Checking symbols with no data_type filter...")
r = requests.get(f"{BASE}/symbols", params={"exchange": "aster_futures"})
print(f"  Status: {r.status_code}")
if r.ok:
    print(json.dumps(r.json(), indent=2)[:1000])

# Check download path format
print("\n[*] Trying a sample download path...")
sample_files = [
    "aster_futures/2025-07-01/00/BTCUSDT_orderbook.parquet.zst",
    "aster_futures/2026-07-01/00/BTCUSDT_orderbook.parquet.zst",
]
for f in sample_files:
    r = requests.get(f"{BASE}/download", params={"file": f})
    print(f"  {f}: HTTP {r.status_code} {r.headers.get('content-type', 'no-ct')}")
