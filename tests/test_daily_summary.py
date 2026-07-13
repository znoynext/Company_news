from datetime import UTC, datetime, timedelta
from pathlib import Path

from dividend_monitor.daily_summary import build_daily_summary, send_daily_summary
from dividend_monitor.models import MonitorState, SentItem
from dividend_monitor.storage import JsonStateStorage


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)


def _item(
    now: datetime,
    title: str,
    category: str = "news",
    importance: str = "medium",
    hours_ago: int = 2,
) -> SentItem:
    return SentItem(
        deduplication_id=title,
        company="A&B",
        title=title,
        url="https://example.com/?q=1&x=2",
        published_at=now - timedelta(hours=hours_ago),
        sent_at=now,
        category=category,
        importance=importance,
    )


def test_daily_summary_counts_categories_and_escapes_event_lines() -> None:
    now = datetime(2026, 7, 14, 8, 17, tzinfo=UTC)
    state = MonitorState(
        sent_items=[
            _item(now, "Dividend <approved>", category="dividend"),
            _item(now, "Report", category="financial_report"),
            _item(now, "Important corporate event", category="corporate"),
            _item(now, "Old event", category="dividend", hours_ago=25),
        ]
    )

    message = build_daily_summary(state, now)

    assert message is not None
    assert "Новых публикаций" in message
    assert ">\n3\n" in message
    assert "Дивидендных событий" in message
    assert "Dividend &lt;approved&gt;" in message
    assert 'href="https://example.com/?q=1&amp;x=2"' in message
    assert "Old event" not in message


def test_daily_summary_without_important_events_uses_fallback() -> None:
    now = datetime(2026, 7, 14, 8, 17, tzinfo=UTC)
    message = build_daily_summary(MonitorState(sent_items=[_item(now, "Regular news")]), now)

    assert message is not None
    assert "За последние 24 часа новых существенных публикаций не обнаружено." in message


def test_daily_summary_is_not_sent_twice_on_same_day(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 8, 17, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    JsonStateStorage(state_path).save(
        MonitorState(
            last_successful_check=now,
            sent_items=[_item(now, "Important", category="corporate")],
        )
    )
    telegram = FakeTelegram()

    assert send_daily_summary(tmp_path, telegram, state_path=Path("state.json"), now=now)
    assert not send_daily_summary(tmp_path, telegram, state_path=Path("state.json"), now=now)
    assert len(telegram.messages) == 1
    assert JsonStateStorage(state_path).load().last_daily_summary_date == "2026-07-14"


def test_stale_workflow_warning_is_not_repeated(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 8, 17, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    JsonStateStorage(state_path).save(MonitorState(last_successful_check=now - timedelta(hours=3)))
    telegram = FakeTelegram()

    assert send_daily_summary(tmp_path, telegram, state_path=Path("state.json"), now=now)
    assert not send_daily_summary(tmp_path, telegram, state_path=Path("state.json"), now=now)
    assert len(telegram.messages) == 2
    assert sum("workflow не выполнялся" in message for message in telegram.messages) == 1
