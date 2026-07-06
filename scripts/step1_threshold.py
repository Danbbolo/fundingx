"""
Step 1: Derive trading threshold from Aster Pro mode real fees.

Source: https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees.md
Raw values fetched on 2026-07-06.
"""

# ============================================================
# RAW VALUES FROM ASTER DOCS (USDT-Perpetual Contracts / Pro mode)
# ============================================================

MAKER_FEE = 0.0       # 0%   — decimal: 0.0
TAKER_FEE = 0.0004   # 0.04% — decimal: 0.0004

print("=" * 60)
print("STEP 1: Fee → Threshold Derivation")
print("=" * 60)
print()
print("SOURCE: https://docs.asterdex.com/trading/perpetuals/fees-and-specs/fees.md")
print("FETCHED: 2026-07-06")
print()
print("--- RAW VALUES (USDT-Perpetual Contracts / Pro mode) ---")
print(f"  Maker fee : 0%     (decimal: {MAKER_FEE})")
print(f"  Taker fee : 0.04%  (decimal: {TAKER_FEE:.4f} = {TAKER_FEE})")
print()

# ============================================================
# DERIVATION
# ============================================================

# We enter and exit as taker (market orders for speed around settlement)
round_trip_taker = 2 * TAKER_FEE

print("--- DERIVATION ---")
print(f"  Round-trip taker fee = 2 × taker_fee")
print(f"                       = 2 × {TAKER_FEE}")
print(f"                       = {round_trip_taker}")
print(f"                       = {round_trip_taker * 100:.4f}%")
print()

# Threshold = round-trip × 3
# (the strategy doc says: "Threshold = round-trip taker fee × 3")
threshold = round_trip_taker * 3
threshold = round(threshold, 6)  # avoid floating point noise

print(f"  Threshold = round_trip × 3")
print(f"            = {round_trip_taker} × 3")
print(f"            = {threshold}")
print(f"            = {threshold * 100:.4f}%")
print()

print("=" * 60)
print(f"  RESULT: Threshold = {threshold} (decimal)")
print(f"          Threshold = {threshold * 100:.4f}%")
print("=" * 60)
print()
print("NOTE: No interval scaling.")
print("Fees are per-trade regardless of funding interval (1h/4h/8h).")
print("A funding rate must be >= this threshold (in absolute value)")
print("to cover round-trip fees × 3.")
