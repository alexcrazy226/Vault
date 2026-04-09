import logging
import socket
import threading
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vault_app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS


logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str = TELEGRAM_BOT_TOKEN, chat_ids: list[str] | None = None) -> None:
        self.bot_token = bot_token
        self.chat_ids = chat_ids if chat_ids is not None else TELEGRAM_CHAT_IDS

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_ids)

    def notify_failed_login(self, username: str, reason: str, attempts: int) -> None:
        if not self.enabled:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        host = socket.gethostname()
        local_ip = "unknown"
        try:
            local_ip = socket.gethostbyname(host)
        except socket.gaierror:
            logger.debug("Could not resolve local hostname for Telegram alert.")

        message = (
            "Failed login alert\n"
            f"Username: {username or '<empty>'}\n"
            f"Reason: {reason}\n"
            f"Attempts in a row: {attempts}\n"
            f"Machine: {host}\n"
            f"Local IP: {local_ip}\n"
            f"Time: {timestamp}"
        )

        thread = threading.Thread(target=self._send_async, args=(message,), daemon=True)
        thread.start()

    def _send_async(self, message: str) -> None:
        for chat_id in self.chat_ids:
            payload = urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
            request = Request(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                data=payload,
                method="POST",
            )
            try:
                urlopen(request, timeout=5).read()
            except OSError as exc:
                logger.warning("Telegram notification failed: %s", exc)
