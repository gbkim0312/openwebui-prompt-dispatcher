from typing import Protocol

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage


class MessageChannelPort(Protocol):
    @property
    def channel_type(self) -> str: ...
    def send(self, target: str, message: OutboundMessage) -> DeliveryReceipt: ...
