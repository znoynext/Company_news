"""Deterministic summaries without an LLM."""

import re
from html import unescape


def summarize(text: str, max_length: int = 500) -> str:
    cleaned = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= max_length:
        return cleaned
    shortened = cleaned[: max_length - 1].rsplit(" ", 1)[0].rstrip()
    return f"{shortened}…"
