"""Conservative parser for verified official company news pages."""

import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig
from .base import Source, SourceHttpError, source_http_client
from .parsing import category_from_text, normalize_url, parse_date

_DATE_PATTERN = re.compile(
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}\s+[A-Za-zА-Яа-яЁё]+\s+\d{4})"
)
_SKIP_SUFFIXES = (".pdf", ".xlsx", ".xls", ".doc", ".docx", ".zip", ".jpg", ".png")
_NAVIGATION_TITLES = {"все результаты", "all results", "все новости", "all news"}
_SOURCE_SELECTORS = {
    "lukoil-official-news": "article, .news-item, .press-release",
    "x5-official-news": "article, .news-item, .news-card",
    "headhunter-official-news": "article, .news-item, .press-center__item",
    "interrao-official-news": "article, .news-item, .news-list__item",
}
_MAX_REPORT_PAGE_REQUESTS = 5
LOGGER = logging.getLogger(__name__)


class OfficialNewsListSource(Source):
    """Parse article links only when the page exposes a publication date nearby."""

    def __init__(self, config: SourceConfig, company: Company) -> None:
        self.config = config
        self.company = company

    def fetch(self) -> list[Publication]:
        if not self.config.url:
            raise ValueError(f"Official news source '{self.config.id}' requires url")
        with source_http_client(
            self.config.timeout_seconds,
            max_requests=1 + _MAX_REPORT_PAGE_REQUESTS,
            max_retries=self.config.max_retries,
        ) as client:
            response = client.get(str(self.config.url))
            soup = BeautifulSoup(response.text, "html.parser")
            discovered_at = datetime.now(UTC)
            publications: list[Publication] = []
            seen_urls: set[str] = set()
            report_pages_requested = 0
            containers = soup.select(_SOURCE_SELECTORS.get(self.config.id, "article, .news-item"))
            if not containers:
                containers = soup.select("a[href]")
            for container in containers:
                link = container if container.name == "a" else container.select_one("a[href]")
                if link is None:
                    continue
                title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
                href = link.get("href", "").strip()
                if (
                    len(title) < 12
                    or not href
                    or href.casefold().startswith(("mailto:", "javascript:"))
                    or title.casefold() in _NAVIGATION_TITLES
                ):
                    continue
                url = normalize_url(href, str(self.config.url))
                if (
                    not self._is_article_url(url)
                    or url.casefold().endswith(_SKIP_SUFFIXES)
                    or url in seen_urls
                ):
                    continue
                context = ""
                for _ in range(3):
                    context = re.sub(r"\s+", " ", container.get_text(" ", strip=True))
                    if _DATE_PATTERN.search(context):
                        break
                    if not container.parent:
                        break
                    container = container.parent
                date_match = _DATE_PATTERN.search(context)
                if not date_match:
                    continue
                published_at = parse_date(date_match.group(0))
                if published_at is None:
                    continue
                category = category_from_text(f"{title} {context}", self.config.categories[0])
                if (
                    category == "financial_report"
                    and report_pages_requested < _MAX_REPORT_PAGE_REQUESTS
                ):
                    report_pages_requested += 1
                    try:
                        report_response = client.get(url)
                    except SourceHttpError as exc:
                        LOGGER.info("Could not load report page %s: %s", url, exc)
                    else:
                        report_text = BeautifulSoup(report_response.text, "html.parser").get_text(
                            " ", strip=True
                        )
                        if report_text:
                            context = re.sub(r"\s+", " ", report_text)
                seen_urls.add(url)
                publications.append(
                    Publication(
                        source_id=self.config.id,
                        company=self.company.name,
                        ticker=self.company.ticker,
                        category=category,
                        title=title,
                        description=context,
                        published_at=published_at,
                        url=HttpUrl(url),
                        external_id=url,
                        discovered_at=discovered_at,
                        source_type="official_html",
                        reliability="medium",
                    )
                )
        return publications

    def _is_article_url(self, url: str) -> bool:
        """Reject navigation, archives, and off-domain links before they become news."""
        source = urlsplit(str(self.config.url))
        candidate = urlsplit(url)
        if candidate.hostname != source.hostname or candidate.path.rstrip(
            "/"
        ) == source.path.rstrip("/"):
            return False
        path = candidate.path.casefold()
        return not any(marker in path for marker in ("/search", "/archive", "/tag", "/all-"))
