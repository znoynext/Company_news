"""Deterministic daily Telegram summary built from persisted monitor state."""

# Keep the notification template readable despite escaped Russian literals.
# ruff: noqa: E501

import argparse
import html
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import MonitorState, SentItem
from .storage import JsonStateStorage
from .telegram import TelegramClient, TelegramConfigurationError

LOGGER = logging.getLogger(__name__)
_SUMMARY_LIMIT = 4096


def _in_last_24_hours(item: SentItem, now: datetime) -> bool:
    published_at = item.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return now - timedelta(hours=24) <= published_at.astimezone(UTC) <= now


def _is_important(item: SentItem) -> bool:
    return item.category in {"dividend", "financial_report", "corporate"} or item.importance == "high"


def _event_line(item: SentItem) -> str:
    company = html.escape(item.company, quote=True)
    title = html.escape(item.title, quote=True)
    if item.url:
        url = html.escape(item.url, quote=True)
        source = f' <a href="{url}">\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a</a>'
    else:
        source = ""
    return f"• <b>{company}</b> — {title}{source}"


def build_daily_summary(state: MonitorState, now: datetime | None = None) -> str | None:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    summary_date = checked_at.date().isoformat()
    if state.last_daily_summary_date == summary_date:
        return None

    events = [item for item in state.sent_items if _in_last_24_hours(item, checked_at)]
    important_events = [item for item in events if _is_important(item)]
    if not important_events:
        return (
            "<b>\U0001f305 \u0421\u0432\u043e\u0434\u043a\u0430 \u043f\u043e \u043f\u043e\u0440\u0442\u0444\u0435\u043b\u044e</b>\n\n"
            "<b>\u041f\u0435\u0440\u0438\u043e\u0434:</b>\n\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 24 \u0447\u0430\u0441\u0430\n\n"
            "\u0417\u0430 \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 24 \u0447\u0430\u0441\u0430 \u043d\u043e\u0432\u044b\u0445 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0445 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0439 \u043d\u0435 \u043e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d\u043e."
        )

    dividends = sum(item.category == "dividend" for item in events)
    reports = sum(item.category == "financial_report" for item in events)
    other_important = sum(
        item.category not in {"dividend", "financial_report"} for item in important_events
    )
    header = (
        "<b>\U0001f305 \u0421\u0432\u043e\u0434\u043a\u0430 \u043f\u043e \u043f\u043e\u0440\u0442\u0444\u0435\u043b\u044e</b>\n\n"
        "<b>\u041f\u0435\u0440\u0438\u043e\u0434:</b>\n\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 24 \u0447\u0430\u0441\u0430\n\n"
        f"<b>\u041d\u043e\u0432\u044b\u0445 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0439:</b>\n{len(events)}\n\n"
        f"<b>\u0414\u0438\u0432\u0438\u0434\u0435\u043d\u0434\u043d\u044b\u0445 \u0441\u043e\u0431\u044b\u0442\u0438\u0439:</b>\n{dividends}\n\n"
        f"<b>\u041e\u0442\u0447\u0451\u0442\u043e\u0432:</b>\n{reports}\n\n"
        f"<b>\u0414\u0440\u0443\u0433\u0438\u0445 \u0432\u0430\u0436\u043d\u044b\u0445 \u0441\u043e\u0431\u044b\u0442\u0438\u0439:</b>\n{other_important}\n\n"
        "<b>\u0412\u0430\u0436\u043d\u044b\u0435 \u0441\u043e\u0431\u044b\u0442\u0438\u044f:</b>"
    )
    message = header
    for item in sorted(important_events, key=lambda value: value.published_at, reverse=True):
        line = _event_line(item)
        candidate = f"{message}\n{line}"
        if len(candidate) > _SUMMARY_LIMIT:
            break
        message = candidate
    return message


def send_daily_summary(
    root: Path,
    telegram: TelegramClient,
    state_path: Path = Path("data/state.json"),
    now: datetime | None = None,
) -> bool:
    storage = JsonStateStorage(root / state_path)
    state = storage.load()
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    message = build_daily_summary(state, checked_at)
    if message is None:
        LOGGER.info("Daily summary already sent for %s", checked_at.date())
        return False
    telegram.send_message(message)
    state.last_daily_summary_date = checked_at.date().isoformat()
    storage.save(state)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one daily portfolio summary")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        telegram = TelegramClient.from_environment()
    except TelegramConfigurationError as exc:
        parser.error(str(exc))
    send_daily_summary(args.root, telegram)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
