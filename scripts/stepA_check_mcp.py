"""Test MCP server for snapshot-at-timestamp capability."""
import json
import requests

MCP_URL = "https://www.cryptohftdata.com/mcp"
API_KEY = "2845d16a0479fc66dc89c01eccc8a3d3434e199828de1c8f168dacfca4a0e0ec"

# Test: list tools via MCP
print("[*] Listing MCP tools...")
r = requests.post(MCP_URL, json={
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
}, headers={"Content-Type": "application/json", "X-API-Key": API_KEY}, timeout=15)
print(f"Status: {r.status_code}")
if r.ok:
    data = r.json()
    if "result" in data and "tools" in data["result"]:
        for tool in data["result"]["tools"]:
            print(f"  - {tool['name']}: {tool.get('description', '')[:100]}")
    else:
        print(json.dumps(data, indent=2)[:2000])
else:
    print(r.text[:500])
