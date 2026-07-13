"""Strict data models used by the monitor."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Category = Literal["news", "financial_report", "dividend", "corporate"]
Importance = Literal["low", "medium", "high"]
SourceType = Literal["fixture", "rss", "official_html"]
Reliability = Literal["high", "medium", "low"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Company(StrictModel):
    name: str = Field(min_length=1)
    ticker: str = Field(min_length=1, pattern=r"^[A-Z0-9.]+$")


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
    source_status: dict[str, SourceStatus] = Field(default_factory=dict)
