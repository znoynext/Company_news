import json

import httpx
import pytest

from dividend_monitor.telegram import TelegramClient, TelegramConfigurationError


def test_missing_telegram_environment_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(TelegramConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient.from_environment()


def test_send_message_uses_html_parse_mode() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = TelegramClient(
        "token",
        "chat",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.send_message("<b>Новости</b>")

    payload = json.loads(requests[0].content)
    assert payload["text"] == "<b>Новости</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True
