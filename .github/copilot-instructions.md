# FundingX — Copilot Instructions

## Project Overview
FundingX is a crypto funding fee arbitrage strategy project. Code is written locally and deployed to Azure for execution.

## Stack
- **Language**: Python 3.11+
- **Packaging**: pyproject.toml (setuptools)
- **Deployment**: Azure Container Instances / Azure App Service
- **Config**: YAML + environment variables

## Conventions
- Use type hints everywhere.
- Follow PEP 8 / Black formatting.
- Tests in `tests/` using pytest.
- Strategy configs in `config/` as YAML files.
- Secrets via `.env` file (never commit).
- Run locally with `python -m fundingx`, deploy via Docker to Azure.
- **Always read `fundingxnotes.md` at the start of a new session** for full context, progress, and checkpoint state.
- Strategy spec lives in `STRATEGY.md` — follow the pipeline steps in order, one task per prompt.
