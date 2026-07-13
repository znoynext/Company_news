"""Small Telegram Bot API client."""

import os
import time
from typing import Any

import httpx


class TelegramConfigurationError(ValueError):
    """Raised when required Telegram environment variables are missing."""


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        client: httpx.Client | None = None,
        max_retries: int = 2,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        self._max_retries = max_retries

    @classmethod
    def from_environment(cls) -> "TelegramClient":
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", token),
                ("TELEGRAM_CHAT_ID", chat_id),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise TelegramConfigurationError(f"Missing required environment variable(s): {joined}")
        return cls(token, chat_id)

    def send_message(self, text: str) -> None:
        if len(text) > 4096:
            raise ValueError("Telegram message exceeds the 4096-character limit")
        endpoint = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(endpoint, json=payload)
                retryable_status = response.status_code in {429, 500, 502, 503, 504}
                if retryable_status and attempt < self._max_retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                response.raise_for_status()
                body: Any = response.json()
                if not body.get("ok", False):
                    raise RuntimeError("Telegram API rejected the message")
                return
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
                if attempt >= self._max_retries:
                    raise
                time.sleep(min(2**attempt, 4))
        raise RuntimeError("Telegram message was not sent")
