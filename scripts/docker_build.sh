#!/usr/bin/env bash
# Build the Docker image for fundingx
set -euo pipefail

IMAGE_NAME="${1:-fundingx}"
TAG="${2:-latest}"

echo "=== Building Docker image: ${IMAGE_NAME}:${TAG} ==="
docker build -t "${IMAGE_NAME}:${TAG}" .

echo "=== Done. Run with: docker run --env-file .env ${IMAGE_NAME}:${TAG} ==="
