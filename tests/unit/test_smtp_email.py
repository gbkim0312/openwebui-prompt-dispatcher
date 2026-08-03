from email.message import EmailMessage
from typing import Self

import pytest

from prompt_dispatcher.adapters.outbound.channels.smtp_email import SmtpEmailChannel
from prompt_dispatcher.domain.delivery import OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError


class FakeSmtp:
    def __init__(self) -> None:
        self.ehlo_calls = 0
        self.tls_started = False
        self.credentials: tuple[str, str] | None = None
        self.sent: EmailMessage | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def ehlo(self) -> None:
        self.ehlo_calls += 1

    def starttls(self, **_: object) -> None:
        self.tls_started = True

    def login(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent = message


def test_smtp_email_sends_to_configured_recipients() -> None:
    client = FakeSmtp()
    channel = SmtpEmailChannel(
        "smtp.gmail.com",
        587,
        "sender@example.com",
        "app-password",
        "sender@example.com",
        {"personal": ("one@example.com", "two@example.com")},
        smtp_factory=lambda *_args, **_kwargs: client,  # type: ignore[arg-type]
    )

    receipt = channel.send("personal", OutboundMessage("뉴스", "메일 본문"))

    assert receipt.external_id
    assert client.tls_started
    assert client.ehlo_calls == 2
    assert client.credentials == ("sender@example.com", "app-password")
    assert client.sent is not None
    assert client.sent["To"] == "one@example.com, two@example.com"
    assert client.sent["Subject"] == "뉴스"
    assert client.sent.get_content().strip() == "메일 본문"


def test_smtp_email_rejects_unknown_target() -> None:
    channel = SmtpEmailChannel(
        "smtp.example.com", 587, "sender", "secret", "sender@example.com", {}
    )

    with pytest.raises(ChannelDeliveryError, match="not configured"):
        channel.send("personal", OutboundMessage("제목", "본문"))
