"""Moscow Exchange official RSS adapter."""

from datetime import UTC, datetime

import feedparser
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig
from .base import Source, source_http_client
from .parsing import category_from_text, normalize_url


class MoexRssSource(Source):
    def __init__(self, config: SourceConfig, company: Company) -> None:
        self.config = config
        self.company = company

    def fetch(self) -> list[Publication]:
        if not self.config.url:
            raise ValueError(f"RSS source '{self.config.id}' requires url")
        with source_http_client(
            self.config.timeout_seconds, max_requests=1, max_retries=self.config.max_retries
        ) as client:
            response = client.get(str(self.config.url))
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid RSS response from {self.config.id}")
        discovered_at = datetime.now(UTC)
        publications: list[Publication] = []
        for entry in parsed.entries:
            date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if not date_struct:
                continue
            published_at = datetime(*date_struct[:6], tzinfo=UTC)
            raw_url = entry.get("link")
            url = normalize_url(raw_url) if raw_url else None
            combined = f"{entry.get('title', '')} {entry.get('summary', '')}"
            publications.append(
                Publication(
                    source_id=self.config.id,
                    company=self.company.name,
                    ticker=self.company.ticker,
                    category=category_from_text(combined, self.config.categories[0]),
                    title=entry.get("title", "Без заголовка"),
                    description=entry.get("summary", ""),
                    published_at=published_at,
                    url=HttpUrl(url) if url else None,
                    external_id=entry.get("id") or entry.get("guid"),
                    discovered_at=discovered_at,
                    source_type="rss",
                    reliability="high",
                )
            )
        return publications
