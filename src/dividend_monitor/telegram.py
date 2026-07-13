"""Small Telegram Bot API client."""

import os
import time
from typing import Any

import httpx


class TelegramConfigurationError(ValueError):
    """Raised when required Telegram environment variables are missing."""


class TelegramDeliveryError(RuntimeError):
    """Raised without exposing the secret-bearing Telegram request URL."""


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

    def send_message(self, text: str) -> int | str:
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
                    time.sleep(_retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                body: Any = response.json()
                if not body.get("ok", False):
                    raise RuntimeError("Telegram API rejected the message")
                message_id = body.get("result", {}).get("message_id")
                return message_id if isinstance(message_id, int) else "sent"
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
                if attempt >= self._max_retries:
                    raise TelegramDeliveryError("Telegram API request failed") from None
                time.sleep(min(2**attempt, 4))
            except httpx.HTTPError:
                raise TelegramDeliveryError("Telegram API request failed") from None
        raise RuntimeError("Telegram message was not sent")


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Prefer Telegram's explicit flood-control delay over exponential backoff."""
    try:
        retry_after = response.json().get("parameters", {}).get("retry_after")
        if isinstance(retry_after, int | float) and retry_after >= 0:
            return min(float(retry_after), 60.0)
    except (TypeError, ValueError):
        pass
    return float(min(2**attempt, 4))
