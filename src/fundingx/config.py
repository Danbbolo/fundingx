"""Configuration loader — reads YAML + env vars into a typed model."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ExchangeConfig(BaseModel):
    name: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True


class StrategyParams(BaseModel):
    """Strategy-specific parameters (extend as you define the strategy)."""

    min_funding_rate: float = 0.0005
    max_position_size: float = 1000.0
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    check_interval_seconds: int = 60


class AppConfig(BaseModel):
    mode: str = "paper"
    log_level: str = "INFO"
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    strategy: StrategyParams = Field(default_factory=StrategyParams)


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    """Load config from a YAML file and return an AppConfig instance."""
    p = Path(path)
    if not p.exists():
        print(f"[config] {p} not found — using defaults")
        return AppConfig()

    with open(p) as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(**raw)
