from pathlib import Path

import pytest

from dividend_monitor.config import load_companies, load_sources


def test_load_yaml_configs() -> None:
    root = Path(__file__).parents[1]
    companies = load_companies(root / "config/companies.yaml")
    sources = load_sources(root / "config/sources.yaml")
    assert companies.companies[0].ticker == "SBER"
    assert {company.ticker for company in companies.companies} >= {
        "LKOH",
        "TRNFP",
        "X5",
        "TATNP",
        "HEAD",
        "IRAO",
        "NMTP",
    }
    assert sources.sources[0].type == "fixture"
    assert sources.sources[-1].status == "limited"


def test_production_rejects_an_enabled_fixture(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text(
        "version: 1\nenvironment: production\nsources:\n"
        "  - id: fixture\n    name: Fixture\n    type: fixture\n    enabled: true\n"
        "    path: test.xml\n    companies: [SBER]\n    categories: [news]\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden in production"):
        load_sources(config)
