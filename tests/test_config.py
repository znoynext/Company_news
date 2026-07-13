from pathlib import Path

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
