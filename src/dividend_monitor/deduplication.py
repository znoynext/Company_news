"""Stable publication fingerprints, state checks, and retention cleanup."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import MonitorState, Publication, SentItem

_TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
    "referrer",
    "yclid",
}


def normalize_url(url: str) -> str:
    """Return a stable URL without tracking noise or a fragment."""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_PARAMETERS
    ]
    query.sort()
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _normalized_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).casefold()


def normalized_title_hash(title: str) -> str:
    return hashlib.sha256(_normalized_title(title).encode("utf-8")).hexdigest()


def fingerprint(publication: Publication) -> str:
    published_at = publication.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    components = {
        "normalized_url": normalize_url(str(publication.url)) if publication.url else "",
        "source_id": publication.source_id.strip(),
        "publication_id": publication.external_id.strip() if publication.external_id else "",
        "title_hash": normalized_title_hash(publication.title),
        "published_at": published_at.astimezone(UTC).isoformat(),
    }
    payload = json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _legacy_deduplication_id(publication: Publication) -> str:
    if publication.external_id:
        source = f"{publication.source_id}:external:{publication.external_id.strip()}"
    elif publication.url:
        source = f"url:{normalize_url(str(publication.url))}"
    else:
        source = "|".join(
            [publication.ticker, publication.title.casefold(), publication.published_at.isoformat()]
        )
    return f"sha256:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"


def deduplication_id(publication: Publication) -> str:
    return fingerprint(publication)


def is_new(publication: Publication, state: MonitorState) -> bool:
    identifier = fingerprint(publication)
    legacy_identifier = _legacy_deduplication_id(publication)
    return not any(
        item.fingerprint == identifier
        or (item.fingerprint is None and item.deduplication_id == legacy_identifier)
        for item in state.sent_items
    )


def mark_sent(
    publication: Publication,
    state: MonitorState,
    now: datetime | None = None,
    telegram_message_status: str | None = None,
) -> None:
    sent_at = now or datetime.now(UTC)
    state.sent_items.append(
        SentItem(
            deduplication_id=deduplication_id(publication),
            company=publication.company,
            title=publication.title,
            url=str(publication.url) if publication.url else None,
            published_at=publication.published_at,
            sent_at=sent_at,
            source_id=publication.source_id,
            publication_id=publication.external_id,
            source_url=str(publication.url) if publication.url else None,
            fingerprint=fingerprint(publication),
            telegram_message_status=telegram_message_status or "sent",
            category=publication.category,
            importance=publication.importance,
            dividend_status=(
                publication.dividend_event.status if publication.dividend_event else None
            ),
        )
    )


def cleanup_old_state(
    state: MonitorState, now: datetime | None = None, retention_days: int = 180
) -> int:
    """Drop sent-item history older than the retention window."""
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = checked_at - timedelta(days=retention_days)
    original_count = len(state.sent_items)
    state.sent_items = [
        item
        for item in state.sent_items
        if (item.sent_at.replace(tzinfo=UTC) if item.sent_at.tzinfo is None else item.sent_at)
        .astimezone(UTC)
        >= cutoff
    ]
    return original_count - len(state.sent_items)
