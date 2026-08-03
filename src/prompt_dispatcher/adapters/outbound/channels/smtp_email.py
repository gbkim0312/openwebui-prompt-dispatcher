import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import make_msgid

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError


class SmtpEmailChannel:
    channel_type = "email"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
        targets: dict[str, tuple[str, ...]],
        use_tls: bool = True,
        timeout_seconds: float = 30,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self._host, self._port, self._username, self._password = host, port, username, password
        self._from, self._targets, self._tls, self._timeout, self._factory = (
            from_address,
            targets,
            use_tls,
            timeout_seconds,
            smtp_factory,
        )

    def send(self, target: str, message: OutboundMessage) -> DeliveryReceipt:
        try:
            recipients = self._targets[target]
        except KeyError as exc:
            raise ChannelDeliveryError(f"Email target is not configured: {target}") from exc
        if not all((self._host, self._username, self._password, self._from, recipients)):
            raise ChannelDeliveryError("SMTP email channel is not fully configured")
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = self._from, ", ".join(recipients), message.title
        email["Message-ID"] = make_msgid()
        email.set_content(message.body)
        try:
            with self._factory(self._host, self._port, timeout=self._timeout) as client:
                client.ehlo()
                if self._tls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                client.login(self._username, self._password)
                client.send_message(email)
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            raise ChannelDeliveryError("SMTP email delivery failed") from exc
        return DeliveryReceipt(str(email["Message-ID"]))
