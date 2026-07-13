"""Deterministic comparisons for financial-report metrics."""

from collections.abc import Iterable
from decimal import Decimal

from .financial_reports import metric_pairs
from .models import FinancialComparison, FinancialMetric, ReportPeriodKind


def calculate_comparisons(
    current: Iterable[FinancialMetric],
    previous_year: Iterable[FinancialMetric],
    period_kind: ReportPeriodKind,
    previous_quarter: Iterable[FinancialMetric] | None = None,
) -> list[FinancialComparison]:
    comparisons: list[FinancialComparison] = []
    for kind, metrics in (("yoy", previous_year), ("qoq", previous_quarter or [])):
        if kind == "qoq" and period_kind != "quarter":
            continue
        for name, (current_metric, previous_metric) in metric_pairs(current, metrics).items():
            delta = current_metric.value - previous_metric.value
            percent = (
                None
                if previous_metric.value == 0
                else (delta / previous_metric.value) * Decimal("100")
            )
            comparisons.append(
                FinancialComparison(
                    name=name,
                    current=current_metric,
                    previous=previous_metric,
                    delta=delta,
                    change_percent=percent,
                    comparison_period=previous_metric.period,
                    comparison_kind=kind,
                )
            )
    return comparisons
