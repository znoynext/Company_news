from datetime import UTC, datetime
from pathlib import Path

from dividend_monitor.runner import format_test_message, run


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
