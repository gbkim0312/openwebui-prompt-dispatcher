import re
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape

from prompt_dispatcher.domain.delivery import DeliveryReceipt, OutboundMessage
from prompt_dispatcher.domain.errors import ChannelDeliveryError

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_UNORDERED_ITEM = re.compile(r"^\s*[-*+]\s+(.+)$")
_ORDERED_ITEM = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline_markdown(value: str) -> str:
    """Render a conservative, safe subset of Markdown for HTML email."""
    rendered = escape(value)
    rendered = _LINK.sub(
        lambda match: (
            f'<a href="{escape(match.group(2), quote=True)}" '
            'style="color:#1565c0;text-decoration:underline">'
            f"{match.group(1)}</a>"
        ),
        rendered,
    )
    rendered = re.sub(
        r"`([^`]+)`", r'<code style="background:#eef2f6;padding:1px 4px">\1</code>', rendered
    )
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", rendered)


def markdown_to_email_html(markdown: str) -> str:
    """Create a self-contained HTML alternative while retaining a plain-text part."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None
    code: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{'<br>'.join(_inline_markdown(line) for line in paragraph)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items and list_tag:
            blocks.append(f"<{list_tag}>{''.join(f'<li>{item}</li>' for item in list_items)}</{list_tag}>")
        list_items.clear()
        list_tag = None

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code:
                blocks.append(
                    '<pre style="white-space:pre-wrap;background:#f3f5f7;padding:12px;border-radius:6px">'
                    f"<code>{escape(chr(10).join(code))}</code></pre>"
                )
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if heading := _HEADING.match(line):
            flush_paragraph()
            flush_list()
            level = min(len(heading.group(1)) + 1, 6)
            blocks.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        item_match = _UNORDERED_ITEM.match(line) or _ORDERED_ITEM.match(line)
        if item_match:
            tag = "ul" if _UNORDERED_ITEM.match(line) else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            flush_paragraph()
            list_tag = tag
            list_items.append(_inline_markdown(item_match.group(1)))
            continue
        if line.strip() in {"---", "***", "___"}:
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
            continue
        paragraph.append(line)
    if in_code:
        blocks.append(
            '<pre style="white-space:pre-wrap;background:#f3f5f7;padding:12px;border-radius:6px">'
            f"<code>{escape(chr(10).join(code))}</code></pre>"
        )
    flush_paragraph()
    flush_list()
    return (
        '<!doctype html><html><body style="font-family:-apple-system,BlinkMacSystemFont,'
        "'Segoe UI',sans-serif;line-height:1.6;color:#18212b;max-width:760px;margin:auto;padding:20px\">"
        f"{''.join(blocks)}</body></html>"
    )


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
        email.add_alternative(markdown_to_email_html(message.body), subtype="html")
        try:
            with self._factory(self._host, self._port, timeout=self._timeout) as client:
                client.ehlo()
                if self._tls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                client.login(self._username, self._password)
                client.send_message(email)
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            detail = str(exc).replace(self._password, "[redacted]").replace("\n", " ")
            raise ChannelDeliveryError(f"SMTP email delivery failed: {detail}") from exc
        return DeliveryReceipt(str(email["Message-ID"]))
