"""Small Bot API client; never put token-bearing request URLs in logs."""

import logging
import time

import requests

LOG = logging.getLogger(__name__)
READ_METHODS = frozenset({"getMe", "getChat", "getChatMember"})
TRANSIENT_STATUS_CODES = frozenset({500, 502, 503, 504})
MAX_ATTEMPTS = 3


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, *, read_only: bool = False):
        if not token or not chat_id:
            raise TelegramError("BOT_TOKEN and CHAT_ID must both be configured")
        self._base_url = f"https://api.telegram.org/bot{token}/"
        self._chat_id = chat_id
        self._read_only = read_only
        self._session = requests.Session()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._session.close()

    def _retry_read(self, method: str, attempt: int, reason: str) -> bool:
        if method not in READ_METHODS or attempt >= MAX_ATTEMPTS - 1:
            return False
        delay = 2 ** (attempt + 1)
        LOG.warning(
            "Telegram %s: %s; retrying read-only check in %ds (%d/%d)",
            method,
            reason,
            delay,
            attempt + 1,
            MAX_ATTEMPTS - 1,
        )
        time.sleep(delay)
        return True

    def _call(self, method: str, payload: dict) -> dict:
        if self._read_only and method not in READ_METHODS:
            raise TelegramError("Read-only verification cannot send or modify Telegram data")
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._session.post(
                    self._base_url + method, json=payload, timeout=(10, 30)
                )
            except requests.RequestException as exc:
                if isinstance(
                    exc, (requests.ConnectionError, requests.Timeout)
                ) and self._retry_read(method, attempt, type(exc).__name__):
                    continue
                # A timed-out send may already have reached Telegram. Do not
                # immediately retry an ambiguous request or expose its URL/token.
                raise TelegramError(
                    f"Telegram {method}: network failure ({type(exc).__name__})"
                ) from None
            # Gateways may return an HTML error page rather than Bot API JSON.
            if response.status_code in TRANSIENT_STATUS_CODES and self._retry_read(
                method, attempt, f"HTTP {response.status_code}"
            ):
                continue
            try:
                data = response.json()
            except ValueError:
                raise TelegramError(
                    f"Telegram {method}: invalid JSON (HTTP {response.status_code})"
                ) from None
            if not isinstance(data, dict):
                raise TelegramError(f"Telegram {method}: unexpected response")
            if response.ok and data.get("ok") is True:
                result = data.get("result")
                if not isinstance(result, dict):
                    raise TelegramError(f"Telegram {method}: missing result")
                return result
            code = data.get("error_code", response.status_code)
            if not isinstance(code, int):
                code = response.status_code
            if code in TRANSIENT_STATUS_CODES and self._retry_read(
                method, attempt, f"API error {code}"
            ):
                continue
            if code == 429 and attempt < MAX_ATTEMPTS - 1:
                parameters = data.get("parameters")
                delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
                if isinstance(delay, (int, float)) and 0 < delay <= 120:
                    time.sleep(delay)
                    continue
            # Do not echo a remote description, which may contain sensitive data.
            raise TelegramError(f"Telegram {method}: API rejected request (code {code})")
        raise TelegramError(f"Telegram {method}: retry limit reached")

    def verify(self) -> None:
        """Read-only check: authenticate and verify access/posting permission."""
        bot = self._call("getMe", {})
        if not isinstance(bot.get("id"), int):
            raise TelegramError("Telegram getMe: missing bot ID")
        chat = self._call("getChat", {"chat_id": self._chat_id})
        member = self._call("getChatMember", {"chat_id": self._chat_id, "user_id": bot["id"]})
        if member.get("status") not in {"creator", "administrator", "member"}:
            raise TelegramError("Bot is not an unrestricted member of the configured chat")
        if chat.get("type") == "channel" and not (
            member.get("status") == "creator"
            or (member.get("status") == "administrator" and member.get("can_post_messages") is True)
        ):
            raise TelegramError("Bot does not have permission to post in the configured channel")

    def send(self, message: str) -> None:
        if not message or len(message.encode("utf-16-le")) // 2 > 4096:
            raise TelegramError("Article message is empty or exceeds Telegram's size limit")
        result = self._call("sendMessage", {"chat_id": self._chat_id, "text": message})
        if not isinstance(result.get("message_id"), int):
            raise TelegramError("Telegram sendMessage: delivery was not acknowledged")
