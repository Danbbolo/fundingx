#!/usr/bin/env bash
# === Azure Container Instance Deployment ===
# Usage: ./azure/deploy.sh [image-tag]
set -euo pipefail

# ——— Config ——————————————————————————————————————————————
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-fundingx-rg}"
ACR_NAME="${AZURE_CONTAINER_REGISTRY:-fundingxregistry}"
IMAGE_TAG="${1:-latest}"
CONTAINER_NAME="fundingx"
IMAGE="${ACR_NAME}.azurecr.io/fundingx:${IMAGE_TAG}"

echo "=== Deploying fundingx to Azure Container Instances ==="
echo "  Resource Group : ${RESOURCE_GROUP}"
echo "  Image          : ${IMAGE}"

# ——— Ensure ACR exists ——————————————————————————————————
az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" >/dev/null 2>&1 || {
    echo "[*] Creating Azure Container Registry: ${ACR_NAME}"
    az acr create \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${ACR_NAME}" \
        --sku Basic \
        --admin-enabled true
}

# ——— Push image ————————————————————————————————————————
echo "[*] Pushing image to ACR..."
az acr login --name "${ACR_NAME}"
docker tag "fundingx:${IMAGE_TAG}" "${IMAGE}"
docker push "${IMAGE}"

# ——— Deploy container ——————————————————————————————————
echo "[*] Deploying container..."
az container create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${CONTAINER_NAME}" \
    --image "${IMAGE}" \
    --registry-login-server "${ACR_NAME}.azurecr.io" \
    --registry-username "${ACR_NAME}" \
    --registry-password "$(az acr credential show --name "${ACR_NAME}" --query passwords[0].value -o tsv)" \
    --cpu 1 \
    --memory 1 \
    --environment-variables \
        STRATEGY_MODE=live \
        LOG_LEVEL=INFO \
    --restart-policy Always \
    --location eastus

echo "=== Deployment complete. Check status with: ==="
echo "  az container show --resource-group ${RESOURCE_GROUP} --name ${CONTAINER_NAME} --query instanceView.state"
