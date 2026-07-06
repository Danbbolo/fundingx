"""Debug: check timestamp alignment in LABUSDT orderbook file."""
import io
import requests
import pyarrow.parquet as pq
import zstandard as zstd
from datetime import datetime, timezone

KEY = open("/home/azureuser/.env").read().split("=", 1)[1].strip()
r = requests.get(
    "https://api.cryptohftdata.com/download",
    params={"file": "aster_futures/2026-06-24/12/LABUSDT_orderbook.parquet.zst", "api_key": KEY},
    timeout=60,
)
df = pq.read_table(io.BytesIO(zstd.decompress(r.content))).to_pandas()

rt_min = df["received_time"].min()
rt_max = df["received_time"].max()
et_min = df["event_time"].min()
et_max = df["event_time"].max()

print(f"received_time range (ns): {rt_min} - {rt_max}")
print(f"event_time range (ms):    {et_min} - {et_max}")
print(f"received_time as dates: {datetime.fromtimestamp(rt_min/1e9, tz=timezone.utc)} - {datetime.fromtimestamp(rt_max/1e9, tz=timezone.utc)}")
print(f"event_time as dates:    {datetime.fromtimestamp(et_min/1e3, tz=timezone.utc)} - {datetime.fromtimestamp(et_max/1e3, tz=timezone.utc)}")

# Settlement at 12:00 UTC June 24
# fundingTime for LABUSDT 2026-06-24T12:00:00
settlement_ms = 1750766400000
t5_ns = (settlement_ms - 5 * 60 * 1000) * 1_000_000  # T-5min in nanoseconds
print(f"\nSettlement (ms): {settlement_ms} = {datetime.fromtimestamp(settlement_ms/1e3, tz=timezone.utc)}")
print(f"T-5min (ns):     {t5_ns}")
print(f"T-5min in range of received_time? {rt_min} <= {t5_ns} <= {rt_max}")
print(f"  -> {rt_min <= t5_ns <= rt_max}")

# Try event_time instead
t5_et_ms = settlement_ms - 5 * 60 * 1000
t5_et_ns = t5_et_ms * 1_000_000
print(f"\nT-5min (et_ms):  {t5_et_ms} = {datetime.fromtimestamp(t5_et_ms/1e3, tz=timezone.utc)}")
rows_before = df[df["event_time"] <= t5_et_ms]
print(f"Rows with event_time <= T-5min: {len(rows_before)}")
