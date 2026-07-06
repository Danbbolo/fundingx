"""Download and inspect one Aster order book parquet to see format/columns/depth."""
import io
import requests

try:
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False

BASE = "https://api.cryptohftdata.com"
FILE = "aster_futures/2026-07-01/00/BTCUSDT_orderbook.parquet.zst"

print(f"[*] Downloading: {FILE}")
r = requests.get(f"{BASE}/download", params={"file": FILE}, timeout=60)
print(f"Status: {r.status_code}, Size: {len(r.content)} bytes, Content-Type: {r.headers.get('content-type')}")

if not r.ok:
    print(f"Error: {r.text[:500]}")
    exit(1)

# Try to decompress and read parquet
import zstandard as zstd
decompressed = zstd.decompress(r.content)
print(f"Decompressed size: {len(decompressed)} bytes")

if HAS_PYARROW:
    table = pq.read_table(io.BytesIO(decompressed))
    print(f"\nSchema:\n{table.schema}")
    print(f"\nRows: {table.num_rows}")
    print(f"Columns: {table.num_columns}")
    df = table.to_pandas()
    print(f"\nFirst 3 rows:")
    print(df.head(3).to_string())
    print(f"\nColumn dtypes:")
    print(df.dtypes)
else:
    print("pyarrow not installed, showing raw bytes preview...")
    print(decompressed[:500])
