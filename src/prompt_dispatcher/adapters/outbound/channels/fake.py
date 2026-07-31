from dataclasses import dataclass

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError


@dataclass(frozen=True)
class SentMessage:
    target: str
    title: str
    body: str


class FakeMessageChannel:
    channel_type = "fake"

    def __init__(self, fail_targets: set[str] | None = None) -> None:
        self.sent_messages: list[SentMessage] = []
        self._fail_targets = fail_targets or set()

    def send(self, target: str, message: OutboundMessage) -> DeliveryReceipt:
        if not target:
            raise ChannelDeliveryError("Target is required")
        if target in self._fail_targets:
            raise ChannelDeliveryError(f"Configured fake failure: {target}")
        self.sent_messages.append(SentMessage(target, message.title, message.body))
        return DeliveryReceipt(f"fake-{len(self.sent_messages)}")
