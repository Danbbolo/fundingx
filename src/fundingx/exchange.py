"""Exchange client wrapper — thin layer over ccxt for funding rate queries."""

from __future__ import annotations

from typing import Any

import ccxt

from fundingx.config import ExchangeConfig


class ExchangeClient:
    """Async-friendly exchange client for funding rate operations."""

    def __init__(self, config: ExchangeConfig) -> None:
        self._config = config
        exchange_class = getattr(ccxt, config.name, None)
        if exchange_class is None:
            raise ValueError(f"Unsupported exchange: {config.name}")

        params: dict[str, Any] = {
            "apiKey": config.api_key or None,
            "secret": config.api_secret or None,
            "enableRateLimit": True,
        }
        if config.testnet:
            params["sandbox"] = True

        self._exchange: ccxt.Exchange = exchange_class(params)

    @property
    def exchange(self) -> ccxt.Exchange:
        return self._exchange

    def get_funding_rates(self, symbols: list[str]) -> dict[str, float]:
        """Return current funding rates for the given symbols."""
        rates: dict[str, float] = {}
        for symbol in symbols:
            try:
                info = self._exchange.fetch_funding_rate(symbol)
                rates[symbol] = info.get("fundingRate", 0.0)
            except Exception as exc:
                rates[symbol] = 0.0
                print(f"[exchange] Failed to fetch rate for {symbol}: {exc}")
        return rates
