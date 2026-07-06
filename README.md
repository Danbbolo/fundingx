# FundingX

Crypto funding fee arbitrage strategy — code locally, deploy to Azure.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt
pip install -e .

# 3. Copy env template and fill in your keys
cp .env.example .env

# 4. Run locally (paper mode)
python -m fundingx --config config/default.yaml --mode paper
```

## Project Structure

```
fundingx/
├── src/fundingx/          # Main Python package
│   ├── __init__.py
│   ├── __main__.py        # CLI entrypoint
│   ├── config.py          # YAML config loader
│   ├── logging.py         # Structured logging (structlog)
│   └── exchange.py        # Exchange client (ccxt)
├── config/
│   └── default.yaml       # Default strategy config
├── tests/                 # pytest test suite
├── azure/
│   ├── deploy.sh          # Manual Azure deployment script
│   └── azure-pipelines.yml
├── scripts/
│   ├── run_local.sh
│   └── docker_build.sh
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```

## Deploy to Azure

```bash
# Build Docker image
./scripts/docker_build.sh fundingx latest

# Deploy to Azure Container Instances
./azure/deploy.sh latest
```

## Configuration

Edit `config/default.yaml` to adjust strategy parameters. See `config.py` for all available fields.

## Testing

```bash
pytest
```
