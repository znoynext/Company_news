"""Source contract and local RSS fixture adapter."""

from pathlib import Path
from typing import Protocol

import feedparser
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig


class Source(Protocol):
    def fetch(self) -> list[Publication]:
        """Return normalized publications from the source."""


class FixtureSource:
    def __init__(
        self, config: SourceConfig, companies: dict[str, Company], base_path: Path
    ) -> None:
        if not config.path:
            raise ValueError(f"Fixture source '{config.id}' requires path")
        self.config = config
        self.companies = companies
        self.path = (base_path / config.path).resolve()

    def fetch(self) -> list[Publication]:
        parsed = feedparser.parse(self.path.read_bytes())
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid fixture feed: {self.path}")
        publications: list[Publication] = []
        for entry in parsed.entries:
            for ticker in self.config.companies:
                company = self.companies[ticker]
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not published:
                    raise ValueError(f"Fixture entry has no date: {entry.get('title', '')}")
                from datetime import UTC, datetime

                published_at = datetime(*published[:6], tzinfo=UTC)
                url = entry.get("link")
                publications.append(
                    Publication(
                        company=company.name,
                        ticker=company.ticker,
                        category=self.config.categories[0],
                        title=entry.get("title", "Untitled publication"),
                        description=entry.get("summary", ""),
                        published_at=published_at,
                        url=HttpUrl(url) if url else None,
                        source_id=self.config.id,
                        external_id=entry.get("id") or entry.get("guid"),
                    )
                )
        return publications
