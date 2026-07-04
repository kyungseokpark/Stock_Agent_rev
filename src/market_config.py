"""Market-specific configuration helpers."""

from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATHS = {
    "us": "configs/config_us.yaml",
    "kr": "configs/config_kr.yaml",
}


def resolve_config_path(market: str) -> str:
    try:
        return CONFIG_PATHS[market]
    except KeyError as exc:
        raise ValueError(f"Unsupported market: {market}") from exc


def load_config(config_path: str | Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_market_label(config: dict) -> str:
    return config.get("market", {}).get("label", "미국장")


def get_currency(config: dict) -> str:
    return config.get("market", {}).get("currency", "USD")
