import smtplib
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

    receipt = channel.send(
        "personal", OutboundMessage("뉴스", "# 메일 제목\n\n- **핵심**: [출처](https://example.com)")
    )

    assert receipt.external_id
    assert client.tls_started
    assert client.ehlo_calls == 2
    assert client.credentials == ("sender@example.com", "app-password")
    assert client.sent is not None
    assert client.sent["To"] == "one@example.com, two@example.com"
    assert client.sent["Subject"] == "뉴스"
    assert client.sent.get_body(("plain",)).get_content().strip().startswith("# 메일 제목")
    html = client.sent.get_body(("html",)).get_content()
    assert "<h2>메일 제목</h2>" in html
    assert "<strong>핵심</strong>" in html
    assert 'href="https://example.com"' in html


def test_smtp_email_rejects_unknown_target() -> None:
    channel = SmtpEmailChannel(
        "smtp.example.com", 587, "sender", "secret", "sender@example.com", {}
    )

    with pytest.raises(ChannelDeliveryError, match="not configured"):
        channel.send("personal", OutboundMessage("제목", "본문"))


def test_smtp_email_accepts_a_recipient_list_as_target() -> None:
    client = FakeSmtp()
    channel = SmtpEmailChannel(
        "smtp.example.com",
        587,
        "sender@example.com",
        "secret",
        "sender@example.com",
        {},
        smtp_factory=lambda *_args, **_kwargs: client,  # type: ignore[arg-type]
    )

    channel.send("one@example.com, Two <two@example.com>", OutboundMessage("제목", "본문"))

    assert client.sent is not None
    assert client.sent["To"] == "one@example.com, two@example.com"


def test_smtp_email_error_includes_safe_server_reason() -> None:
    class RejectingSmtp(FakeSmtp):
        def login(self, username: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, f"invalid password: {password}")

    channel = SmtpEmailChannel(
        "smtp.example.com",
        587,
        "sender",
        "secret-value",
        "sender@example.com",
        {"personal": ("recipient@example.com",)},
        smtp_factory=lambda *_args, **_kwargs: RejectingSmtp(),  # type: ignore[arg-type]
    )

    with pytest.raises(ChannelDeliveryError) as error:
        channel.send("personal", OutboundMessage("제목", "본문"))

    assert "535" in str(error.value)
    assert "[redacted]" in str(error.value)
    assert "secret-value" not in str(error.value)
