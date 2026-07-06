"""Step A: Explore cryptohftdata.com for Aster historical order book data."""
import json
import requests

BASE = "https://api.cryptohftdata.com"

print("=" * 60)
print("Step A: Exploring cryptohftdata.com for Aster data")
print("=" * 60)

# 1. Check status — what exchanges/data types are available
print("\n[*] Checking /status...")
r = requests.get(f"{BASE}/status", params={"lookback_hours": 24})
print(f"Status code: {r.status_code}")
if r.ok:
    data = r.json()
    for ex in data.get("exchanges", []):
        name = ex.get("exchange", "")
        if "aster" in name.lower():
            print(f"\n--- ASTER EXCHANGE DATA ---")
            print(json.dumps(ex, indent=2))
else:
    print(f"Error: {r.text[:500]}")

# 2. List Aster symbols for different data types
print("\n[*] Checking /symbols for Aster...")
for dtype in ["orderbook", "trades", "ticker", "mark_price", "open_interest"]:
    r = requests.get(f"{BASE}/symbols", params={"exchange": "aster", "data_type": dtype})
    if r.ok:
        data = r.json()
        symbols = data.get("symbols", [])
        print(f"  {dtype:<20s}: {len(symbols)} symbols", end="")
        if symbols:
            print(f"  (first 5: {symbols[:5]})", end="")
        print()
    else:
        print(f"  {dtype:<20s}: HTTP {r.status_code}")

# 3. Check authentication — do we need a key?
print("\n[*] Checking /download without auth...")
r = requests.get(f"{BASE}/download", params={"file": "test"})
print(f"  Status: {r.status_code}")
if r.status_code == 401:
    print("  Auth required — need API key or JWT token")
elif r.status_code == 422:
    print("  Endpoint exists but needs valid file path")

print("\n[+] Done exploring.")
