from dataclasses import dataclass
from datetime import datetime

from .enums import DeliveryStatus


@dataclass(frozen=True)
class OutboundMessage:
    title: str
    body: str


@dataclass(frozen=True)
class DeliveryReceipt:
    external_id: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    channel_type: str
    target: str
    status: DeliveryStatus
    started_at: datetime
    finished_at: datetime
    external_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
