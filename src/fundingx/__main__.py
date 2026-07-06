"""Entrypoint for `python -m fundingx`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fundingx",
        description="Crypto funding fee arbitrage strategy runner",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/default.yaml",
        help="Path to strategy config YAML (default: config/default.yaml)",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default=None,
        help="Override strategy mode from config",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = parse_args(argv)

    from fundingx.config import load_config
    from fundingx.logging import setup_logging

    cfg = load_config(args.config)
    if args.mode:
        cfg.mode = args.mode
    if args.log_level:
        cfg.log_level = args.log_level

    setup_logging(cfg.log_level)

    # TODO: initialise strategy engine and start trading loop
    print(f"[fundingx] Starting in {cfg.mode} mode with config: {args.config}")
    print("[fundingx] Strategy engine not yet implemented — scaffolding ready.")


if __name__ == "__main__":
    main()
