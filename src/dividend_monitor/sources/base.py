"""Source contracts, HTTP policy, and local RSS fixture adapter."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import feedparser
import httpx
from pydantic import HttpUrl

from ..models import Company, Publication, SourceConfig


class Source(Protocol):
    def fetch(self) -> list[Publication]:
        """Return normalized publications from the source."""


class SourceHttpError(RuntimeError):
    """Raised when a public source cannot be fetched safely."""


class SourceHttpClient:
    """Bounded HTTP client shared by source adapters."""

    MAX_RESPONSE_BYTES = 5_000_000

    def __init__(self, timeout_seconds: float, max_requests: int, max_retries: int) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            headers={
                "User-Agent": "DividendMonitor/0.1 (+https://github.com/znoynext/Company_news)",
                "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.1",
            },
            follow_redirects=True,
        )
        self._max_requests = max_requests
        self._max_retries = max_retries
        self._requests = 0

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> httpx.Response:
        if self._requests >= self._max_requests:
            raise SourceHttpError("Source request limit reached")
        self._requests += 1
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(url)
                retryable_status = response.status_code in {429, 500, 502, 503, 504}
                if retryable_status and attempt < self._max_retries:
                    time.sleep(_retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.MAX_RESPONSE_BYTES:
                    raise SourceHttpError("Source response exceeds the configured size limit")
                if len(response.content) > self.MAX_RESPONSE_BYTES:
                    raise SourceHttpError("Source response exceeds the configured size limit")
                content_type = response.headers.get("content-type", "").casefold()
                if content_type and not any(
                    value in content_type for value in ("xml", "html", "text/", "json")
                ):
                    raise SourceHttpError("Source returned an unsupported content type")
                return response
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                if attempt >= self._max_retries:
                    raise SourceHttpError(f"Temporary network error for {url}") from exc
                time.sleep(min(2**attempt, 4))
        raise SourceHttpError(f"Could not fetch {url}")


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Use server-provided retry timing while keeping source retries bounded."""
    try:
        return min(max(float(response.headers.get("Retry-After", "")), 0.0), 60.0)
    except ValueError:
        return float(min(2**attempt, 4))


@contextmanager
def source_http_client(
    timeout_seconds: float, max_requests: int, max_retries: int
) -> Iterator[SourceHttpClient]:
    client = SourceHttpClient(timeout_seconds, max_requests, max_retries)
    try:
        yield client
    finally:
        client.close()


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
                published_at = datetime(*published[:6], tzinfo=UTC)
                url = entry.get("link")
                publications.append(
                    Publication(
                        source_id=self.config.id,
                        company=company.name,
                        ticker=company.ticker,
                        category=self.config.categories[0],
                        title=entry.get("title", "Untitled publication"),
                        description=entry.get("summary", ""),
                        published_at=published_at,
                        url=HttpUrl(url) if url else None,
                        external_id=entry.get("id") or entry.get("guid"),
                        discovered_at=datetime.now(UTC),
                        source_type="fixture",
                        reliability="low",
                    )
                )
        return publications
