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

    return CompaniesConfig.model_validate(_load_yaml(path))


def load_sources(path: Path) -> SourcesConfig:
    """Load and validate the sources configuration."""

    return SourcesConfig.model_validate(_load_yaml(path))
