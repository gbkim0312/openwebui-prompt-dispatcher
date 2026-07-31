import httpx

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError

from .telegram import _chunks


class NextcloudTalkChannel:
    channel_type = "nextcloud_talk"

    def __init__(
        self,
        base_url: str,
        targets: dict[str, tuple[str, str, str]],
        verify_tls: bool = True,
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self._url, self._targets, self._timeout = base_url.rstrip("/"), targets, timeout_seconds
        self._client = client or httpx.Client(verify=verify_tls)

    def send(self, target: str, message: OutboundMessage) -> DeliveryReceipt:
        try:
            username, password, room = self._targets[target]
        except KeyError as exc:
            raise ChannelDeliveryError(
                f"Nextcloud Talk target is not configured: {target}"
            ) from exc
        external_id = None
        try:
            for part in _chunks(message.body, 3900):
                response = self._client.post(
                    f"{self._url}/ocs/v2.php/apps/spreed/api/v1/chat/{room}",
                    data={"message": part},
                    auth=(username, password),
                    headers={"OCS-APIRequest": "true", "Accept": "application/json"},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("ocs", {}).get("meta", {}).get("status") not in ("ok", "OK"):
                    raise ValueError("Nextcloud rejected message")
                external_id = str(payload.get("ocs", {}).get("data", {}).get("id", ""))
        except (httpx.HTTPError, ValueError) as exc:
            raise ChannelDeliveryError("Nextcloud Talk delivery failed") from exc
        return DeliveryReceipt(external_id)
