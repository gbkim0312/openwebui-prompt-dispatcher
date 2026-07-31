import httpx

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError


def _chunks(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


class TelegramChannel:
    channel_type = "telegram"

    def __init__(
        self,
        targets: dict[str, tuple[str, str]],
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self._targets, self._timeout, self._client = (
            targets,
            timeout_seconds,
            client or httpx.Client(),
        )

    def send(self, target: str, message: OutboundMessage) -> DeliveryReceipt:
        try:
            token, chat_id = self._targets[target]
        except KeyError as exc:
            raise ChannelDeliveryError(f"Telegram target is not configured: {target}") from exc
        external_id = None
        try:
            for part in _chunks(message.body, 3900):
                response = self._client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": part},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise ValueError("Telegram rejected message")
                external_id = str(payload.get("result", {}).get("message_id", ""))
        except (httpx.HTTPError, ValueError) as exc:
            raise ChannelDeliveryError("Telegram delivery failed") from exc
        return DeliveryReceipt(external_id)
