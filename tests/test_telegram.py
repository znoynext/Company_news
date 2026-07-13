import pytest

from dividend_monitor.telegram import TelegramClient, TelegramConfigurationError


def test_missing_telegram_environment_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient.from_environment()
