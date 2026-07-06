"""Tests for config loading."""

from pathlib import Path

from fundingx.config import AppConfig, load_config


def test_default_config():
    """AppConfig() should return sane defaults."""
    cfg = AppConfig()
    assert cfg.mode == "paper"
    assert cfg.strategy.min_funding_rate == 0.0005


def test_load_config_missing_file(tmp_path: Path):
    """Missing config file should fall back to defaults."""
    cfg = load_config(tmp_path / "nonexistent.yaml")
    assert cfg.mode == "paper"


def test_load_config_from_yaml(tmp_path: Path):
    """Config file values should override defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("mode: live\nlog_level: DEBUG\n")
    cfg = load_config(cfg_file)
    assert cfg.mode == "live"
    assert cfg.log_level == "DEBUG"
