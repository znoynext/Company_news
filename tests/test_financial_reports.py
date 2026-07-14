from datetime import UTC, datetime
from decimal import Decimal

from dividend_monitor.calculations import calculate_comparisons
from dividend_monitor.financial_reports import (
    detect_report_context,
    extract_explicit_text_metrics,
    extract_structured_metrics,
)
from dividend_monitor.models import FinancialMetric, MonitorState, Publication
from dividend_monitor.runner import (
    _enrich_report_context,
    _remember_report,
    _report_with_comparisons,
    format_message,
)

SOURCE_URL = "https://example.com/report"


def test_report_context_detects_period_and_standard() -> None:
    assert detect_report_context("Отчетность по МСФО за 6 месяцев 2025 года") == (
        "2025 H1",
        "six_months",
        "МСФО",
    )
    assert detect_report_context("IFRS Q1 2026 results")[:2] == ("2026 Q1", "quarter")
    assert detect_report_context("МСФО за 2 квартал 2026 года")[:2] == ("2026 Q2", "quarter")
    assert detect_report_context("РСБУ за 2025 год")[:2] == ("2025 FY", "year")


def test_structured_json_extracts_only_complete_unambiguous_metrics() -> None:
    content = """
    {"metrics": [
      {"name": "revenue", "value": "123.4", "currency": "RUB", "unit": "млн",
       "period": "2025 H1", "standard": "МСФО"},
      {"name": "net_profit", "value": "1,2 / 1,1", "currency": "RUB", "unit": "млн",
       "period": "2025 H1", "standard": "МСФО"}
    ]}
    """

    metrics = extract_structured_metrics(content, SOURCE_URL)

    assert len(metrics) == 1
    assert metrics[0].name == "revenue"
    assert metrics[0].value == Decimal("123.4")
    assert str(metrics[0].source_url) == SOURCE_URL


def test_structured_html_table_is_supported_but_pdf_is_not() -> None:
    html = """
    <table>
      <tr><th>Показатель</th><th>Значение</th><th>Валюта</th><th>Единица</th>
          <th>Период</th><th>Стандарт</th></tr>
      <tr><td>EBITDA</td><td>10</td><td>RUB</td><td>млн</td><td>2025 FY</td><td>РСБУ</td></tr>
    </table>
    """

    assert len(extract_structured_metrics(html, SOURCE_URL)) == 1
    xml = (
        '<report><metric name="net_profit" value="7.5" currency="RUB" unit="mln" '
        'period="2025 FY" standard="RAS" /></report>'
    )
    assert extract_structured_metrics(xml, SOURCE_URL)[0].name == "net_profit"
    assert extract_structured_metrics("%PDF-1.7", SOURCE_URL) == []


def test_explicit_text_metrics_require_period_standard_scale_and_currency() -> None:
    metrics = extract_explicit_text_metrics(
        "Results under IFRS for 2026: revenue amounted to 125.5 bln RUB. "
        "Net profit was 25 bln RUB.",
        SOURCE_URL,
        period="2026 FY",
        standard="МСФО",
    )

    assert [(metric.name, metric.value, metric.currency, metric.unit) for metric in metrics] == [
        ("revenue", Decimal("125.5"), "RUB", "млрд"),
        ("net_profit", Decimal("25"), "RUB", "млрд"),
    ]
    assert (
        extract_explicit_text_metrics(
            "Revenue grew by 25%.", SOURCE_URL, period="2026 FY", standard="МСФО"
        )
        == []
    )


def test_report_enrichment_extracts_explicit_official_metric_for_yoy() -> None:
    publication = Publication(
        source_id="official",
        company="Компания",
        ticker="TEST",
        category="financial_report",
        title="IFRS results for 2026",
        description="Revenue amounted to 125 bln RUB for FY 2026 under IFRS.",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=SOURCE_URL,
    )

    enriched = _enrich_report_context(publication)

    assert enriched.report_period == "2026 FY"
    assert enriched.report_standard == "МСФО"
    assert enriched.report_metrics[0].name == "revenue"
    assert enriched.report_metrics[0].value == Decimal("125")


def _metric(name: str, value: str, period: str) -> FinancialMetric:
    return FinancialMetric(
        name=name,
        value=Decimal(value),
        currency="RUB",
        unit="млн",
        period=period,
        standard="МСФО",
        source_url=SOURCE_URL,
    )


def test_quarter_comparison_prefers_yoy_and_allows_qoq_additionally() -> None:
    comparisons = calculate_comparisons(
        [_metric("revenue", "120", "2026 Q1")],
        [_metric("revenue", "100", "2025 Q1")],
        "quarter",
        previous_quarter=[_metric("revenue", "110", "2025 Q4")],
    )

    assert [item.comparison_kind for item in comparisons] == ["yoy", "qoq"]
    assert comparisons[0].delta == Decimal("20")
    assert comparisons[0].change_percent == Decimal("20")
    assert comparisons[1].delta == Decimal("10")


def test_six_month_comparison_is_yoy_only() -> None:
    comparisons = calculate_comparisons(
        [_metric("net_profit", "80", "2026 H1")],
        [_metric("net_profit", "100", "2025 H1")],
        "six_months",
        previous_quarter=[_metric("net_profit", "60", "2026 Q1")],
    )

    assert len(comparisons) == 1
    assert comparisons[0].comparison_kind == "yoy"
    assert comparisons[0].change_percent == Decimal("-20")


def test_financial_report_without_safe_metrics_uses_fallback_text() -> None:
    message = format_message(
        Publication(
            source_id="reports",
            company="Компания",
            ticker="TEST",
            category="financial_report",
            title="Отчетность за 2025 год по РСБУ",
            description="Опубликован официальный отчет.",
            published_at=datetime(2026, 7, 13, tzinfo=UTC),
            url=SOURCE_URL,
            report_period="2025 FY",
            report_period_kind="year",
            report_standard="РСБУ",
        )
    )

    assert "Проверенные числовые показатели пока не извлечены" in message
    assert "PDF" not in message
    assert SOURCE_URL in message


def test_runner_uses_saved_prior_report_for_yoy_comparison() -> None:
    previous = Publication(
        source_id="reports",
        company="Компания",
        ticker="TEST",
        category="financial_report",
        title="2025 report",
        description="",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        url=SOURCE_URL,
        external_id="previous",
        report_period="2025 FY",
        report_period_kind="year",
        report_standard="МСФО",
        report_metrics=[_metric("revenue", "100", "2025 FY")],
    )
    current = previous.model_copy(
        update={
            "title": "2026 report",
            "external_id": "current",
            "report_period": "2026 FY",
            "report_metrics": [_metric("revenue", "125", "2026 FY")],
        }
    )
    state = MonitorState()
    _remember_report(previous, state)

    result = _report_with_comparisons(current, state)

    assert len(result.report_comparisons) == 1
    assert result.report_comparisons[0].comparison_kind == "yoy"
    assert result.report_comparisons[0].change_percent == Decimal("25")


def test_financial_report_message_shows_metrics_and_yoy_without_document_noise() -> None:
    previous = _metric("revenue", "100", "2025 FY")
    current = _metric("revenue", "125", "2026 FY")
    publication = Publication(
        source_id="reports",
        company="Компания",
        ticker="TEST",
        category="financial_report",
        title="Результаты за 2026 год",
        description="",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url=SOURCE_URL,
        report_period="2026 FY",
        report_standard="МСФО",
        report_metrics=[current],
        report_comparisons=calculate_comparisons([current], [previous], "year"),
    )

    message = format_message(publication)

    assert "Ключевые показатели" in message
    assert "Выручка:</b> 125 RUB" in message
    assert "Динамика" in message
    assert "↑ 25.0% (год к году; 25 RUB)" in message
    assert "PDF" not in message
