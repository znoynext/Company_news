"""MOEX RSS adapter that routes issuer news to matching companies."""

from datetime import UTC, datetime

import feedparser
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig
from .base import Source, source_http_client
from .parsing import category_from_text, normalize_url

COMPANY_ALIASES = {
    "SBER": ("сбербанк", "sberbank"),
    "MOEX": ("московская биржа", "moscow exchange", "moex"),
    "LSNGP": ("ленэнерго", "россети ленэнерго", "lenenergo"),
    "LKOH": ("лукойл", "lukoil"),
    "TRNFP": ("транснефть", "transneft"),
    "X5": ("x5", "икс 5", "x5 group"),
    "TATNP": ("татнефть", "tatneft"),
    "HEAD": ("хэдхантер", "headhunter"),
    "IRAO": ("интер рао", "inter rao"),
    "NMTP": ("нмтп", "новороссийский морской торговый порт", "nmtp"),
}


class MoexCompaniesRssSource(Source):
    def __init__(self, config: SourceConfig, companies: dict[str, Company]) -> None:
        self.config = config
        self.companies = companies

    def fetch(self) -> list[Publication]:
        if not self.config.url:
            raise ValueError(f"MOEX source '{self.config.id}' requires url")
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
            title = entry.get("title", "Без заголовка")
            description = entry.get("summary", "")
            combined = f"{title} {description}".casefold()
            published_at = datetime(*date_struct[:6], tzinfo=UTC)
            raw_url = entry.get("link")
            url = normalize_url(raw_url) if raw_url else None
            for ticker in self.config.companies:
                aliases = (*COMPANY_ALIASES.get(ticker, ()), ticker.casefold())
                if not any(alias in combined for alias in aliases):
                    continue
                company = self.companies[ticker]
                publications.append(
                    Publication(
                        source_id=self.config.id,
                        company=company.name,
                        ticker=ticker,
                        category=category_from_text(combined, self.config.categories[0]),
                        title=title,
                        description=description,
                        published_at=published_at,
                        url=HttpUrl(url) if url else None,
                        external_id=f"{entry.get('id') or entry.get('guid') or raw_url}:{ticker}",
                        discovered_at=discovered_at,
                        source_type="rss",
                        reliability="high",
                    )
                )
        return publications
