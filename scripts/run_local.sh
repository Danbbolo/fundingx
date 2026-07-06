#!/usr/bin/env bash
# Run fundingx locally in paper mode
set -euo pipefail

echo "=== FundingX — Local Run ==="
python -m fundingx --config config/default.yaml --mode paper --log-level DEBUG
