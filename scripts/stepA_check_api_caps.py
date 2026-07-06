"""Explore cryptohftdata API for snapshot-at-timestamp capability."""
import requests

BASE = "https://api.cryptohftdata.com"

print("=" * 60)
print("Checking API capabilities beyond bulk download...")
print("=" * 60)

# 1. Check if there's a snapshot/point-query endpoint
print("\n[*] Testing potential snapshot endpoints...")
test_paths = [
    "/snapshot",
    "/orderbook",
    "/orderbook/snapshot",
    "/depth",
    "/book",
    "/query",
    "/v1/snapshot",
    "/v1/orderbook",
]
for path in test_paths:
    r = requests.get(f"{BASE}{path}", timeout=5)
    print(f"  GET {path:<30s} → {r.status_code}")

# 2. Check if download supports range queries or partial reads
print("\n[*] Testing download with query params...")
test_params = [
    {"file": "aster_futures/2026-07-05/12/LABUSDT_orderbook.parquet.zst", "timestamp": "1783089600000"},
    {"file": "aster_futures/2026-07-05/12/LABUSDT_orderbook.parquet.zst", "limit": "5"},
    {"file": "aster_futures/2026-07-05/12/LABUSDT_orderbook.parquet.zst", "format": "json"},
]
for params in test_params:
    r = requests.get(f"{BASE}/download", params=params, stream=True, timeout=10)
    size = int(r.headers.get("content-length", 0))
    r.close()
    print(f"  params={params} → {r.status_code} size={size/1024:.0f}KB")

# 3. Check the agent skills index for any hidden capabilities
print("\n[*] Checking agent skills index...")
r = requests.get("https://www.cryptohftdata.com/.well-known/agent-skills/index.json")
if r.ok:
    import json
    skills = r.json()
    print(json.dumps(skills, indent=2)[:2000])
else:
    print(f"  Status: {r.status_code}")

# 4. Check if there's a REST query interface in the MCP server card
print("\n[*] Checking MCP server card...")
r = requests.get("https://www.cryptohftdata.com/.well-known/mcp/server-card.json")
if r.ok:
    import json
    card = r.json()
    print(json.dumps(card, indent=2)[:2000])
else:
    print(f"  Status: {r.status_code}")
