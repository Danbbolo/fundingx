"""Inspect order book parquet data format and rows."""
import io
import requests
import pyarrow.parquet as pq
import zstandard as zstd

r = requests.get(
    "https://api.cryptohftdata.com/download",
    params={"file": "aster_futures/2026-07-01/00/BTCUSDT_orderbook.parquet.zst"},
    timeout=60,
)
data = zstd.decompress(r.content)
t = pq.read_table(io.BytesIO(data))
df = t.to_pandas()

print("=== First 10 rows ===")
print(df.head(10).to_string())
print()
print("Unique sides:", df["side"].unique())
print("Unique event_types:", df["event_type"].unique())
ts_min = df["received_time"].min()
ts_max = df["received_time"].max()
print(f"Time range: {ts_min} - {ts_max} ({(ts_max - ts_min) / 1e9:.0f} seconds)")
print(f"Rows: {len(df)}")

# Filter to snapshot-like events
for et in df["event_type"].unique():
    sub = df[df["event_type"] == et]
    print(f"\nevent_type='{et}': {len(sub)} rows")
    print(sub.head(3).to_string())
