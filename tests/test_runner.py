from datetime import UTC, datetime
from pathlib import Path

from dividend_monitor.models import Publication
from dividend_monitor.runner import format_message, format_test_message, run


class FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)


def test_runner_sends_fixture_once(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    telegram = FakeTelegram()
    state_path = tmp_path / "state.json"
    first = run(root, telegram, state_path=state_path)
    second = run(root, telegram, state_path=state_path)
    assert len(telegram.messages) == 1
    assert len(first.sent_items) == 1
    assert len(second.sent_items) == 1
    assert "Сбербанк" in telegram.messages[0]


def test_test_message_contains_connection_details_without_token() -> None:
    message = format_test_message(
        "0.1.0",
        "Dividend monitor",
        datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
    )
    assert message.startswith("✅ Dividend Monitor успешно подключен к Telegram.")
    assert "Время UTC: 2026-07-13T12:30:00Z" in message
    assert "Версия приложения: 0.1.0" in message
    assert "Workflow: Dividend monitor" in message
    assert "TELEGRAM_BOT_TOKEN" not in message


def test_format_message_uses_requested_html_layout_and_escapes_external_text() -> None:
    publication = Publication(
        source_id="fixture",
        company="A&B <Corp>",
        ticker="AB",
        category="news",
        title="<Breaking> & dividend update",
        description="<b>Unsafe</b> & important details",
        published_at=datetime(2026, 7, 13, 12, 30, tzinfo=UTC),
        url="https://example.com/news?a=1&b=2",
        importance="high",
    )

    message = format_message(publication)

    assert message == (
        "<b>📰 A&amp;B &lt;Corp&gt; · news</b>\n\n"
        "&lt;Breaking&gt; &amp; dividend update\n\n"
        "<b>Кратко:</b>\nUnsafe &amp; important details\n\n"
        "<b>Важность:</b>\n🔴 высокая\n\n"
        "<b>Источник:</b>\nhttps://example.com/news?a=1&amp;b=2\n\n"
        "<b>Опубликовано:</b>\n2026-07-13 12:30 UTC"
    )
    assert "<Breaking>" not in message
    assert "<b>Unsafe</b>" not in message


def test_format_message_limits_description_to_500_characters() -> None:
    publication = Publication(
        source_id="fixture",
        company="Company",
        ticker="ABC",
        category="news",
        title="Title",
        description="слово " * 200,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        importance="low",
    )

    message = format_message(publication)
    description = message.split("<b>Кратко:</b>\n", 1)[1].split("\n\n<b>Важность:", 1)[0]

    assert len(description) <= 500
    assert description.endswith("…")


def test_format_message_stays_within_telegram_limit_for_hostile_long_text() -> None:
    publication = Publication(
        source_id="fixture",
        company="<company> & " * 100,
        ticker="ABC",
        category="news",
        title="<title> & " * 1000,
        description="<description> & " * 1000,
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        url="https://example.com/?q=" + ("&x=<value>" * 150),
    )

    assert len(format_message(publication)) <= 4096
