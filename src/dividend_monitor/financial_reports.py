"""Small, conservative helpers for structured financial-report data."""

# Unicode escape-heavy matching tables are kept readable instead of split into opaque builders.
# ruff: noqa: E501

import json
import re
from collections.abc import Iterable
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from .models import FinancialMetric, MetricName, ReportPeriodKind, ReportStandard

_METRIC_ALIASES: dict[MetricName, tuple[str, ...]] = {
    "revenue": ("\u0432\u044b\u0440\u0443\u0447\u043a\u0430", "revenue"),
    "operating_profit": (
        "\u043e\u043f\u0435\u0440\u0430\u0446\u0438\u043e\u043d\u043d\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c",
        "operating profit",
    ),
    "ebitda": ("ebitda",),
    "net_profit": (
        "\u0447\u0438\u0441\u0442\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c",
        "net profit",
    ),
    "free_cash_flow": (
        "\u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0439 \u0434\u0435\u043d\u0435\u0436\u043d\u044b\u0439 \u043f\u043e\u0442\u043e\u043a",
        "free cash flow",
    ),
    "net_debt": ("\u0447\u0438\u0441\u0442\u044b\u0439 \u0434\u043e\u043b\u0433", "net debt"),
    "capital_expenditures": (
        "\u043a\u0430\u043f\u0438\u0442\u0430\u043b\u044c\u043d\u044b\u0435 \u0440\u0430\u0441\u0445\u043e\u0434\u044b",
        "\u043a\u0430\u043f\u0438\u0442\u0430\u043b\u044c\u043d\u044b\u0435 \u0437\u0430\u0442\u0440\u0430\u0442\u044b",
        "capex",
    ),
}


def detect_report_context(
    text: str,
) -> tuple[str | None, ReportPeriodKind | None, ReportStandard | None]:
    normalized = re.sub(r"\s+", " ", text.casefold().replace("\u0451", "\u0435")).strip()
    standard: ReportStandard | None = None
    if re.search(r"\b\u043c\u0441\u0444\u043e\b|ifrs", normalized):
        standard = "\u041c\u0421\u0424\u041e"
    elif re.search(r"\b\u0440\u0441\u0431\u0443\b|ras", normalized):
        standard = "\u0420\u0421\u0411\u0423"

    patterns = (
        (
            "quarter",
            r"(?:\u0437\u0430\s+)?(?:1|i)\s*\u043a\u0432\u0430\u0440\u0442\u0430\u043b(?:\u0430)?\s*(?:20)?(\d{2,4})|\bq1\s*(20\d{2})",
        ),
        (
            "quarter",
            r"(?:\u0437\u0430\s+)?(?:2|ii)\s*\u043a\u0432\u0430\u0440\u0442\u0430\u043b(?:\u0430)?\s*(?:20)?(\d{2,4})|\bq2\s*(20\d{2})",
        ),
        (
            "quarter",
            r"(?:\u0437\u0430\s+)?(?:3|iii)\s*\u043a\u0432\u0430\u0440\u0442\u0430\u043b(?:\u0430)?\s*(?:20)?(\d{2,4})|\bq3\s*(20\d{2})",
        ),
        (
            "quarter",
            r"(?:\u0437\u0430\s+)?(?:4|iv)\s*\u043a\u0432\u0430\u0440\u0442\u0430\u043b(?:\u0430)?\s*(?:20)?(\d{2,4})|\bq4\s*(20\d{2})",
        ),
        (
            "six_months",
            r"(?:\u0437\u0430\s+)?6\s*\u043c\u0435\u0441\u044f\u0446(?:\u0435\u0432|\u0430)?\s*(20\d{2})|\bh1\s*(20\d{2})",
        ),
        (
            "nine_months",
            r"(?:\u0437\u0430\s+)?9\s*\u043c\u0435\u0441\u044f\u0446(?:\u0435\u0432|\u0430)?\s*(20\d{2})|\b9m\s*(20\d{2})",
        ),
        ("year", r"(?:\u0437\u0430\s+)?(?:20\d{2})\s*\u0433\u043e\u0434|\bfy\s*(20\d{2})"),
    )
    for kind, pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        year = next((value for value in match.groups() if value), None)
        if kind == "quarter":
            year_match = re.search(r"20\d{2}", match.group(0))
            if year_match:
                year = year_match.group(0)
        if not year:
            year_match = re.search(r"20\d{2}", match.group(0))
            year = year_match.group(0) if year_match else None
        if not year:
            continue
        marker = {"quarter": "Q", "six_months": "H1", "nine_months": "9M", "year": "FY"}[kind]
        if kind == "quarter":
            quarter = next(
                (
                    str(index)
                    for index, roman in enumerate(("i", "ii", "iii", "iv"), 1)
                    if f"q{index}" in match.group(0)
                    or re.search(
                        rf"(?:{index}|{roman})\s*\u043a\u0432\u0430\u0440\u0442\u0430\u043b",
                        match.group(0),
                    )
                ),
                "1",
            )
            period = f"{year} Q{quarter}"
        else:
            period = f"{year} {marker}"
        return period, kind, standard
    return None, None, standard


def _metric_name(value: str) -> MetricName | None:
    normalized = re.sub(r"\s+", " ", value.casefold().replace("\u0451", "\u0435")).strip()
    for name, aliases in _METRIC_ALIASES.items():
        if normalized == name or normalized in aliases:
            return name
    return None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", text):
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _build_metric(row: dict[str, Any], source_url: HttpUrl) -> FinancialMetric | None:
    name = _metric_name(str(row.get("name", row.get("metric", ""))))
    value = _decimal(row.get("value"))
    currency = str(row.get("currency", "")).strip()
    unit = str(row.get("unit", "")).strip()
    period = str(row.get("period", "")).strip()
    standard = str(row.get("standard", "")).strip()
    if not name or value is None or not currency or not unit or not period:
        return None
    if standard.casefold() in {"ras", "\u0440\u0441\u0431\u0443"}:
        standard = "\u0420\u0421\u0411\u0423"
    elif standard.casefold() in {"ifrs", "\u043c\u0441\u0444\u043e"}:
        standard = "\u041c\u0421\u0424\u041e"
    else:
        return None
    return FinancialMetric(
        name=name,
        value=value,
        currency=currency,
        unit=unit,
        period=period,
        standard=standard,
        source_url=source_url,
    )


def _json_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("metrics"), list):
        return [row for row in payload["metrics"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def extract_structured_metrics(content: str, source_url: HttpUrl) -> list[FinancialMetric]:
    """Extract only explicit rows from JSON, XML, or HTML tables; never PDF/text."""
    if content.lstrip().startswith("%PDF"):
        return []
    rows: list[dict[str, Any]] = []
    with suppress(json.JSONDecodeError, TypeError):
        rows = _json_rows(json.loads(content))
    if not rows:
        with suppress(ElementTree.ParseError):
            root = ElementTree.fromstring(content)
            rows = [element.attrib for element in root.iter("metric")]
    if not rows:
        soup = BeautifulSoup(content, "html.parser")
        for table in soup.select("table"):
            table_rows = table.select("tr")
            headers = (
                [
                    cell.get_text(" ", strip=True).casefold()
                    for cell in table_rows[0].select("th,td")
                ]
                if table_rows
                else []
            )
            required = {
                "\u043f\u043e\u043a\u0430\u0437\u0430\u0442\u0435\u043b\u044c",
                "\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435",
                "\u0432\u0430\u043b\u044e\u0442\u0430",
                "\u0435\u0434\u0438\u043d\u0438\u0446\u0430",
                "\u043f\u0435\u0440\u0438\u043e\u0434",
                "\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442",
            }
            if not required.issubset(headers):
                continue
            for row in table_rows[1:]:
                values = [cell.get_text(" ", strip=True) for cell in row.select("td,th")]
                if len(values) == len(headers):
                    rows.append(dict(zip(headers, values, strict=True)))
            if rows:
                break
    normalized_rows = []
    for row in rows:
        normalized_rows.append(
            {
                "name": row.get(
                    "name",
                    row.get(
                        "metric",
                        row.get("\u043f\u043e\u043a\u0430\u0437\u0430\u0442\u0435\u043b\u044c", ""),
                    ),
                ),
                "value": row.get(
                    "value", row.get("\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435")
                ),
                "currency": row.get(
                    "currency", row.get("\u0432\u0430\u043b\u044e\u0442\u0430", "")
                ),
                "unit": row.get("unit", row.get("\u0435\u0434\u0438\u043d\u0438\u0446\u0430", "")),
                "period": row.get("period", row.get("\u043f\u0435\u0440\u0438\u043e\u0434", "")),
                "standard": row.get(
                    "standard", row.get("\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442", "")
                ),
            }
        )
    return [metric for row in normalized_rows if (metric := _build_metric(row, source_url))]


def metric_pairs(
    current: Iterable[FinancialMetric], previous: Iterable[FinancialMetric]
) -> dict[MetricName, tuple[FinancialMetric, FinancialMetric]]:
    previous_by_name = {
        (metric.name, metric.standard, metric.currency, metric.unit): metric for metric in previous
    }
    return {
        metric.name: (metric, previous_by_name[key])
        for metric in current
        if (key := (metric.name, metric.standard, metric.currency, metric.unit)) in previous_by_name
    }
