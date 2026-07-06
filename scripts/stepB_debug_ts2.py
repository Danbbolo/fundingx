"""Check: what are the actual fundingTime values for LABUSDT?"""
import requests
from datetime import datetime, timezone

r = requests.get("https://fapi.asterdex.com/fapi/v1/fundingRate", params={"symbol": "LABUSDT", "limit": 5})
data = r.json()
print("Latest 5 LABUSDT funding entries:")
for e in data:
    ts_ms = e["fundingTime"]
    ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    print(f"  fundingTime={ts_ms} = {ts_dt}  rate={e['fundingRate']}")

# Also check a very recent one
import time
r2 = requests.get("https://fapi.asterdex.com/fapi/v1/fundingRate", params={"symbol": "LABUSDT", "limit": 3, "endTime": int(time.time() * 1000)})
data2 = r2.json()
print("\nMost recent entries:")
for e in data2:
    ts_ms = e["fundingTime"]
    ts_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    print(f"  fundingTime={ts_ms} = {ts_dt}  rate={e['fundingRate']}")

# What does the parquet file cover?
print("\nFile: aster_futures/2026-06-24/12/LABUSDT")
print("  Covers: 2026-06-24 12:00 to 12:59 UTC")
print("  Settlement should be at: 2026-06-24 12:00 UTC")
print("  fundingTime for that would be ~1750766400000 (2025) or ~1782302400000 (2026)")
