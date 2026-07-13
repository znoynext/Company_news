from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from dividend_monitor.models import Company, SourceConfig
from dividend_monitor.sources import (
    EdisclosureReportsSource,
    LenenergoPressSource,
    MoexCompaniesRssSource,
    MoexRssSource,
    OfficialNewsListSource,
    SberOfficialHtmlSource,
)
from dividend_monitor.sources.parsing import parse_date


class FixtureResponse:
    def __init__(self, path: Path) -> None:
        self.content = path.read_bytes()
        self.text = self.content.decode("utf-8")


class FixtureClient:
    def __init__(self, response: FixtureResponse) -> None:
        self.response = response

    def get(self, url: str) -> httpx.Response:
        return self.response  # type: ignore[return-value]


def source_config(source_id: str, source_type: str, categories: list[str]) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name=source_id,
        type=source_type,
        url="https://example.invalid/source",
        companies=["TEST"],
        categories=categories,
        max_retries=0,
    )


def patch_http_client(monkeypatch, module, response: FixtureResponse) -> None:
    @contextmanager
    def fake_client(*args, **kwargs) -> Iterator[FixtureClient]:
        yield FixtureClient(response)

    monkeypatch.setattr(module, "source_http_client", fake_client)


def test_moex_rss_adapter_uses_saved_xml(monkeypatch) -> None:
    from dividend_monitor.sources import moex

    patch_http_client(
        monkeypatch, moex, FixtureResponse(Path("tests/fixtures/moex_investor_rss.xml"))
    )
    source = MoexRssSource(
        source_config("moex", "rss", ["news", "financial_report"]),
        Company(name="Тест", ticker="TEST"),
    )
    item = source.fetch()[0]
    assert item.source_id == "moex"
    assert item.source_type == "rss"
    assert item.category == "financial_report"
    assert item.published_at == datetime(2026, 7, 13, 9, 45, tzinfo=UTC)


def test_lenenergo_adapter_uses_saved_html(monkeypatch) -> None:
    from dividend_monitor.sources import lenenergo

    patch_http_client(
        monkeypatch, lenenergo, FixtureResponse(Path("tests/fixtures/lenenergo_press.html"))
    )
    source = LenenergoPressSource(
        source_config("lenenergo", "official_html", ["news"]),
        Company(name="Тест", ticker="TEST"),
    )
    item = source.fetch()[0]
    assert item.source_type == "official_html"
    assert item.category == "financial_report"
    assert str(item.url).endswith("/press/lenenergo/999999.html")


def test_sber_adapter_uses_saved_html(monkeypatch) -> None:
    from dividend_monitor.sources import sber

    patch_http_client(
        monkeypatch, sber, FixtureResponse(Path("tests/fixtures/sber_disclosure.html"))
    )
    source = SberOfficialHtmlSource(
        source_config("sber", "official_html", ["corporate"]),
        Company(name="Тест", ticker="TEST"),
    )
    item = source.fetch()[0]
    assert item.external_id == "fixture-sber-001"
    assert item.category == "corporate"
    assert item.discovered_at.tzinfo is not None


def test_official_news_adapter_requires_a_nearby_date(monkeypatch) -> None:
    from dividend_monitor.sources import official_news

    patch_http_client(
        monkeypatch, official_news, FixtureResponse(Path("tests/fixtures/official_news.html"))
    )
    source = OfficialNewsListSource(
        source_config("official", "official_html", ["news", "financial_report"]),
        Company(name="Тест", ticker="TEST"),
    )

    item = source.fetch()[0]

    assert item.title == "Компания опубликовала финансовые результаты"
    assert item.published_at == datetime(2026, 7, 13, tzinfo=UTC)
    assert item.category == "financial_report"


def test_moex_companies_adapter_filters_unrequested_issuers(monkeypatch) -> None:
    from dividend_monitor.sources import moex_companies

    patch_http_client(
        monkeypatch,
        moex_companies,
        FixtureResponse(Path("tests/fixtures/moex_companies_rss.xml")),
    )
    source = MoexCompaniesRssSource(
        SourceConfig(
            id="moex-all",
            name="moex-all",
            type="rss",
            url="https://example.invalid/source",
            companies=["TRNFP"],
            categories=["news", "financial_report"],
            max_retries=0,
        ),
        {"TRNFP": Company(name="Транснефть", ticker="TRNFP")},
    )

    items = source.fetch()

    assert len(items) == 2
    assert items[0].ticker == "TRNFP"


def test_edisclosure_adapter_reads_only_issuer_reports(monkeypatch) -> None:
    from dividend_monitor.sources import edisclosure

    patch_http_client(
        monkeypatch,
        edisclosure,
        FixtureResponse(Path("tests/fixtures/edisclosure_reports.html")),
    )
    source = EdisclosureReportsSource(
        source_config("reports", "official_html", ["financial_report"]),
        Company(name="Транснефть", ticker="TRNFP"),
    )

    items = source.fetch()

    assert len(items) == 1
    assert items[0].category == "financial_report"
    assert items[0].published_at == datetime(2026, 4, 29, tzinfo=UTC)


def test_unknown_date_is_not_replaced_with_current_time() -> None:
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("not a date") is None
