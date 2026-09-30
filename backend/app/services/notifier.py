import logging

import httpx

logger = logging.getLogger("easybid")


class Notifier:
    """Telegram alerts. Does nothing unless a bot token and chat id are configured."""

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        if not (self._token and self._chat_id):
            return
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                res = await http.post(
                    f"https://api.telegram.org/bot{self._token}/sendMessage",
                    json={"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True},
                )
                res.raise_for_status()
        except httpx.HTTPError as e:
            # A failed alert must never break the pipeline.
            logger.warning("Telegram notification failed: %r", e)
