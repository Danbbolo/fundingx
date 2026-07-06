"""Debug: check actual fundingTime values from the script's perspective."""
import requests
import time
from datetime import datetime, timezone, timedelta

COINS = ["TAIKOUSDT", "LABUSDT", "HUSDT", "BIRBUSDT"]
cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp() * 1000)
now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

print(f"Now (UTC): {datetime.now(timezone.utc)}")
print(f"Cutoff ms: {cutoff_ms} = {datetime.fromtimestamp(cutoff_ms/1000, tz=timezone.utc)}")

for symbol in COINS:
    r = requests.get("https://fapi.asterdex.com/fapi/v1/fundingRate", params={"symbol": symbol, "limit": 10})
    data = r.json()
    print(f"\n{symbol} latest 10:")
    for e in data[-3:]:
        ts = e["fundingTime"]
        dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
        in_range = "YES" if ts >= cutoff_ms else "NO"
        print(f"  fundingTime={ts} = {dt}  rate={float(e['fundingRate'])*100:.4f}%  in_range={in_range}")
