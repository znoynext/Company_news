"""Parser for issuer reports published by Interfax disclosure pages."""

import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from ..financial_reports import detect_report_context, extract_structured_metrics
from ..models import Company, Publication, SourceConfig
from .base import Source, source_http_client
from .parsing import normalize_url, parse_date


class EdisclosureReportsSource(Source):
    def __init__(self, config: SourceConfig, company: Company) -> None:
        self.config = config
        self.company = company

    def fetch(self) -> list[Publication]:
        if not self.config.url:
            raise ValueError(f"E-disclosure source '{self.config.id}' requires url")
        with source_http_client(
            self.config.timeout_seconds, max_requests=1, max_retries=self.config.max_retries
        ) as client:
            response = client.get(str(self.config.url))

        soup = BeautifulSoup(response.text, "html.parser")
        discovered_at = datetime.now(UTC)
        publications: list[Publication] = []
        seen_urls: set[str] = set()
        for row in soup.select("tr"):
            text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
            normalized_text = text.casefold().replace("ё", "е")
            if "отчет" not in normalized_text or not re.search(
                r"\d{1,2}[./]\d{1,2}[./]\d{4}", text
            ):
                continue
            link = row.select_one("a[href]")
            if not link:
                continue
            url = normalize_url(link.get("href", ""), str(self.config.url))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            date_match = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", text)
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True)) or "Отчёт эмитента"
            report_period, period_kind, report_standard = detect_report_context(text)
            report_url = HttpUrl(url)
            metrics = extract_structured_metrics(str(row), report_url)
            publications.append(
                Publication(
                    source_id=self.config.id,
                    company=self.company.name,
                    ticker=self.company.ticker,
                    category="financial_report",
                    title=title,
                    description=text,
                    published_at=parse_date(date_match.group(0), discovered_at),
                    url=report_url,
                    external_id=url,
                    discovered_at=discovered_at,
                    source_type="official_html",
                    reliability="medium",
                    report_period=report_period,
                    report_period_kind=period_kind,
                    report_standard=report_standard,
                    report_metrics=metrics,
                )
            )
        return publications
