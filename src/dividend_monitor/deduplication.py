"""Stable publication identifiers and state checks."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from .models import MonitorState, Publication, SentItem


def _canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def deduplication_id(publication: Publication) -> str:
    if publication.external_id:
        source = f"{publication.source_id}:external:{publication.external_id.strip()}"
    elif publication.url:
        source = f"url:{_canonical_url(str(publication.url))}"
    else:
        source = "|".join(
            [publication.ticker, publication.title.casefold(), publication.published_at.isoformat()]
        )
    return f"sha256:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def is_new(publication: Publication, state: MonitorState) -> bool:
    identifier = deduplication_id(publication)
    return all(item.deduplication_id != identifier for item in state.sent_items)


def mark_sent(publication: Publication, state: MonitorState, now: datetime | None = None) -> None:
    sent_at = now or datetime.now(UTC)
    state.sent_items.append(
        SentItem(
            deduplication_id=deduplication_id(publication),
            company=publication.company,
            title=publication.title,
            url=str(publication.url) if publication.url else None,
            published_at=publication.published_at,
            sent_at=sent_at,
        )
    )
