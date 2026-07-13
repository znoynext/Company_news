"""Small, deterministic parsing helpers for public sources."""

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from ..models import Category

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def normalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url or "", url.strip())
    parts = urlsplit(absolute)
    query = parse_qs(parts.query)
    safe_query = "&".join(
        f"{key}={value[0]}"
        for key, value in sorted(query.items())
        if not key.lower().startswith("utm_")
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), safe_query, "")
    )


def parse_date(value: str | None, fallback: datetime | None = None) -> datetime:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError, IndexError):
            match = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", value.casefold())
            if match and match.group(2) in MONTHS:
                return datetime(
                    int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)), tzinfo=UTC
                )
            iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", value)
            if iso_match:
                return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=UTC)
            numeric_match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
            if numeric_match:
                return datetime(
                    int(numeric_match.group(3)),
                    int(numeric_match.group(2)),
                    int(numeric_match.group(1)),
                    tzinfo=UTC,
                )
    return fallback or datetime.now(UTC)


def category_from_text(text: str, default: Category = "news") -> Category:
    value = text.casefold()
    if any(word in value for word in ("дивиденд", "dividend")):
        return "dividend"
    if any(
        word in value
        for word in ("отчетност", "отчётност", "финансов", "financial", "results", "ifrs", "рсбу")
    ):
        return "financial_report"
    if any(word in value for word in ("совет директоров", "акционер", "собрани", "корпоратив")):
        return "corporate"
    return default
