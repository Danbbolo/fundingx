"""Check parquet file sizes for our target coins to estimate download cost."""
import requests
from datetime import datetime, timedelta, timezone

BASE = "https://api.cryptohftdata.com"
COINS = ["HOMEUSDT", "TAIKOUSDT", "COAIUSDT", "LABUSDT", "PIPPINUSDT", "HUSDT", "BEATUSDT", "BIRBUSDT", "AIAUSDT"]

# Check one recent hour for each coin
date = "2026-07-05"
hour = "12"

print(f"Checking file sizes for {date} hour {hour}:")
print(f"{'Symbol':<16s} {'Size_KB':>10s} {'Status':>8s}")
print("-" * 36)

for symbol in COINS:
    path = f"aster_futures/{date}/{hour}/{symbol}_orderbook.parquet.zst"
    try:
        r = requests.get(f"{BASE}/download", params={"file": path}, stream=True, timeout=10)
        if r.ok:
            size = int(r.headers.get("content-length", 0))
            r.close()
            print(f"{symbol:<16s} {size/1024:>10,.0f} {'OK':>8s}")
        else:
            r.close()
            print(f"{symbol:<16s} {'?':>10s} {r.status_code:>8d}")
    except Exception as e:
        print(f"{symbol:<16s} {'ERR':>10s} {str(e)[:30]}")
