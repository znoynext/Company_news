"""Strict data models used by the monitor."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Category = Literal["news", "financial_report", "dividend", "corporate"]
Importance = Literal["low", "medium", "high"]
SourceType = Literal["fixture", "rss", "official_html"]
Reliability = Literal["high", "medium", "low"]
SourceAvailability = Literal["working", "limited", "manual", "unavailable"]
ReportStandard = Literal["РСБУ", "МСФО"]
ReportPeriodKind = Literal["quarter", "six_months", "nine_months", "year"]
MetricName = Literal[
    "revenue",
    "operating_profit",
    "ebitda",
    "net_profit",
    "free_cash_flow",
    "net_debt",
    "capital_expenditures",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Company(StrictModel):
    name: str = Field(min_length=1)
    ticker: str = Field(min_length=1, pattern=r"^[A-Z0-9.]+$")


class FinancialMetric(StrictModel):
    name: MetricName
    value: Decimal
    currency: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    period: str = Field(min_length=1)
    standard: ReportStandard
    source_url: HttpUrl


class FinancialComparison(StrictModel):
    name: MetricName
    current: FinancialMetric
    previous: FinancialMetric
    delta: Decimal
    change_percent: Decimal | None = None
    comparison_period: str = Field(min_length=1)
    comparison_kind: Literal["yoy", "qoq"]


class CompaniesConfig(StrictModel):
    companies: list[Company] = Field(min_length=1)


class SourceConfig(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: SourceType
    enabled: bool = True
    path: str | None = None
    url: HttpUrl | None = None
    companies: list[str] = Field(min_length=1)
    categories: list[Category] = Field(min_length=1)
    primary: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    status: SourceAvailability = "working"


class SourcesConfig(StrictModel):
    version: int = Field(ge=1)
    sources: list[SourceConfig]


class Publication(StrictModel):
    source_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    category: Category
    title: str = Field(min_length=1)
    description: str = ""
    published_at: datetime
    url: HttpUrl | None = None
    external_id: str | None = None
    importance: Importance = "medium"
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_type: SourceType = "fixture"
    reliability: Reliability = "low"
    report_period: str | None = None
    report_period_kind: ReportPeriodKind | None = None
    report_standard: ReportStandard | None = None
    report_metrics: list[FinancialMetric] = Field(default_factory=list)
    report_comparisons: list[FinancialComparison] = Field(default_factory=list)


class SentItem(StrictModel):
    deduplication_id: str
    company: str
    title: str
    url: str | None
    published_at: datetime
    sent_at: datetime


class SourceStatus(StrictModel):
    last_checked_at: datetime
    status: Literal["ok", "error"]
    error: str | None = None


class MonitorState(StrictModel):
    schema_version: int = 1
    last_successful_check: datetime | None = None
    last_daily_summary_date: str | None = None
    sent_items: list[SentItem] = Field(default_factory=list)
    financial_reports: list[Publication] = Field(default_factory=list)
    source_status: dict[str, SourceStatus] = Field(default_factory=dict)


class RunStatistics(StrictModel):
    sources_checked: int = Field(default=0, ge=0)
    successful: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    new_publications: int = Field(default=0, ge=0)
    sent: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)
