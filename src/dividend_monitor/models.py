"""Strict data models used by the monitor."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Category = Literal["news", "financial_report", "dividend", "corporate"]
Importance = Literal["low", "medium", "high"]
SourceType = Literal["fixture", "rss", "official_html"]
# "error" remains readable from historical state and is migrated to "failed".
SourceHealth = Literal["ok", "degraded", "failed", "error"]
DeliveryStatus = Literal["pending", "sent", "failed", "dry-run", "filtered", "remembered"]
BootstrapMode = Literal["remember_only", "recent_only", "backfill"]
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
DividendStatus = Literal["recommended", "approved", "cancelled", "paid"]
DividendEventType = Literal[
    "recommendation",
    "approval",
    "cancellation",
    "policy_change",
    "meeting",
    "record_date",
    "payment",
]
ShareType = Literal["ordinary", "preferred", "unspecified"]


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


class DividendEvent(StrictModel):
    status: DividendStatus
    event_type: DividendEventType
    amount_per_share: Decimal | None = None
    currency: str = "RUB"
    share_type: ShareType = "unspecified"
    period: str | None = None
    general_meeting_date: datetime | None = None
    register_close_date: datetime | None = None
    policy_change: str | None = None
    board_recommendation: str | None = None
    shareholder_decision: str | None = None
    rasbu_net_profit: str | None = None
    dividend_base: str | None = None
    preferred_share_payment: str | None = None
    source_url: HttpUrl


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


class AiConfig(StrictModel):
    """Limits that keep optional GitHub Models usage predictable and free-tier friendly."""

    enabled: bool = True
    max_requests_per_run: int = Field(default=10, ge=0, le=100)
    max_requests_per_day: int = Field(default=100, ge=0, le=1_000)
    reserve_requests_for_high_priority: int = Field(default=3, ge=0, le=100)
    max_input_characters: int = Field(default=6_000, ge=100, le=20_000)
    cache_ttl_days: int = Field(default=180, ge=1, le=1_825)
    cache_max_items: int = Field(default=5_000, ge=1, le=20_000)
    enrich_priorities: list[Importance] = Field(default_factory=lambda: ["high", "medium"])
    skip_low_priority_when_budget_low: bool = True


class TelegramConfig(StrictModel):
    max_messages_per_run: int = Field(default=20, ge=1, le=100)
    aggregate_source_errors: bool = True
    group_company_events: bool = True
    # Production YAML opts into digests; preserve legacy minimal configurations.
    send_low_priority_immediately: bool = True


class SourcesConfig(StrictModel):
    version: int = Field(ge=1)
    sources: list[SourceConfig]
    environment: Literal["production", "test"] = "production"
    # Legacy in-memory test configurations omit this field; production YAML
    # explicitly selects remember_only.
    initial_sync_mode: BootstrapMode = "backfill"
    max_item_age_hours: int = Field(default=168, ge=1, le=8_760)
    ai: AiConfig = Field(default_factory=AiConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class Publication(StrictModel):
    source_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    category: Category
    title: str = Field(min_length=1)
    description: str = ""
    ai_summary: str | None = Field(default=None, max_length=500)
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
    dividend_event: DividendEvent | None = None


class SentItem(StrictModel):
    deduplication_id: str
    company: str
    title: str
    url: str | None
    published_at: datetime
    sent_at: datetime
    source_id: str = "legacy"
    publication_id: str | None = None
    source_url: str | None = None
    fingerprint: str | None = None
    telegram_message_status: DeliveryStatus = "sent"
    telegram_message_id: int | None = None
    first_seen_at: datetime | None = None
    category: Category = "news"
    importance: Importance = "medium"
    dividend_status: DividendStatus | None = None


class AiCacheEntry(StrictModel):
    summary: str = Field(min_length=1, max_length=500)
    importance: Importance
    created_at: datetime


class AiUsage(StrictModel):
    date: str | None = None
    requests: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    rate_limit_hits: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class SourceStatus(StrictModel):
    last_checked_at: datetime
    status: SourceHealth
    error: str | None = None
    last_successful_check: datetime | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_degraded_at: datetime | None = None
    consecutive_errors: int = Field(default=0, ge=0)
    failure_alert_sent: bool = False


class SourceResult(StrictModel):
    """Observable result of one source check; no exception is mistaken for success."""

    source_id: str
    status: SourceHealth
    http_status: int | None = None
    fetched_count: int = Field(default=0, ge=0)
    parsed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    new_count: int = Field(default=0, ge=0)
    sent_count: int = Field(default=0, ge=0)
    parse_error_count: int = Field(default=0, ge=0)
    newest_publication_at: datetime | None = None
    content_hash: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None


class MonitorState(StrictModel):
    schema_version: int = 7
    identity_version: int = 2
    last_successful_check: datetime | None = None
    last_run_at: datetime | None = None
    last_fully_successful_run_at: datetime | None = None
    last_degraded_run_at: datetime | None = None
    bootstrap_completed: bool = False
    last_daily_summary_date: str | None = None
    last_weekly_health_report_date: str | None = None
    workflow_alert_sent: bool = False
    ai_failure_alert_sent: bool = False
    ai_last_error: str | None = None
    last_run_duration_seconds: float | None = Field(default=None, ge=0)
    last_run_new_publications: int = Field(default=0, ge=0)
    last_run_telegram_messages: int = Field(default=0, ge=0)
    last_run_errors: int = Field(default=0, ge=0)
    sent_items: list[SentItem] = Field(default_factory=list)
    financial_reports: list[Publication] = Field(default_factory=list)
    source_status: dict[str, SourceStatus] = Field(default_factory=dict)
    ai_cache: dict[str, AiCacheEntry] = Field(default_factory=dict)
    ai_usage: AiUsage = Field(default_factory=AiUsage)
    identity_index: set[str] = Field(default_factory=set)
    source_cursors: dict[str, dict[str, str]] = Field(default_factory=dict)


class RunStatistics(StrictModel):
    sources_checked: int = Field(default=0, ge=0)
    successful: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    new_publications: int = Field(default=0, ge=0)
    sent: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)
