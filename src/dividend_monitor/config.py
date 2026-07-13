"""Configuration loading from YAML files."""

from pathlib import Path
from typing import Any

import yaml

from .models import CompaniesConfig, SourcesConfig


def _load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file not found: {path}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot read configuration file: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")
    return data


def load_companies(path: Path) -> CompaniesConfig:
    """Load and validate the companies configuration."""

    config = CompaniesConfig.model_validate(_load_yaml(path))
    tickers = [company.ticker for company in config.companies]
    if len(tickers) != len(set(tickers)):
        raise ValueError("Company tickers must be unique")
    return config


def load_sources(path: Path, *, company_tickers: set[str] | None = None) -> SourcesConfig:
    """Load and validate the sources configuration."""

    config = SourcesConfig.model_validate(_load_yaml(path))
    source_ids = [source.id for source in config.sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Source ids must be unique")
    if config.ai.reserve_requests_for_high_priority > config.ai.max_requests_per_run:
        raise ValueError("AI high-priority reserve cannot exceed the per-run limit")
    for source in config.sources:
        if source.type == "fixture":
            if not source.path:
                raise ValueError(f"Fixture source '{source.id}' requires path")
            if source.url:
                raise ValueError(f"Fixture source '{source.id}' must not define url")
            if config.environment == "production" and source.enabled:
                raise ValueError("Fixture sources are forbidden in production")
        elif not source.url:
            raise ValueError(f"HTTP source '{source.id}' requires url")
        if company_tickers is not None:
            unknown = set(source.companies) - company_tickers
            if unknown:
                raise ValueError(
                    f"Source '{source.id}' references unknown companies: {sorted(unknown)}"
                )
            if len(source.companies) != len(set(source.companies)):
                raise ValueError(f"Source '{source.id}' lists a company more than once")
    return config
