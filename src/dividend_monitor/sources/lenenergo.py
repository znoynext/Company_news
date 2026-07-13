"""Rosseti Lenenergo official press-page adapter."""

import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig
from .base import Source, source_http_client
from .parsing import category_from_text, normalize_url, parse_date


class LenenergoPressSource(Source):
    def __init__(self, config: SourceConfig, company: Company) -> None:
        self.config = config
        self.company = company

    def fetch(self) -> list[Publication]:
        if not self.config.url:
            raise ValueError(f"Lenenergo source '{self.config.id}' requires url")
        with source_http_client(
            self.config.timeout_seconds, max_requests=1, max_retries=self.config.max_retries
        ) as client:
            response = client.get(str(self.config.url))
        soup = BeautifulSoup(response.text, "html.parser")
        discovered_at = datetime.now(UTC)
        publications: list[Publication] = []
        for link in soup.select("a[href$='.html']"):
            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if len(title) < 8:
                continue
            container = link.parent.get_text(" ", strip=True) if link.parent else title
            url = normalize_url(link.get("href", ""), str(self.config.url))
            publications.append(
                Publication(
                    source_id=self.config.id,
                    company=self.company.name,
                    ticker=self.company.ticker,
                    category=category_from_text(title, self.config.categories[0]),
                    title=title,
                    description=re.sub(r"\s+", " ", container),
                    published_at=parse_date(container, discovered_at),
                    url=HttpUrl(url),
                    external_id=url.rsplit("/", 1)[-1],
                    discovered_at=discovered_at,
                    source_type="official_html",
                    reliability="medium",
                )
            )
        return publications
