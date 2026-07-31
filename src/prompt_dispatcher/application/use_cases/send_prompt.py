import logging
from dataclasses import dataclass

from prompt_dispatcher.application.ports.clock import ClockPort
from prompt_dispatcher.application.ports.openwebui import OpenWebUiPort
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.domain.delivery import OutboundMessage
from prompt_dispatcher.domain.job import ChannelDestination, OpenWebUiRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendPromptCommand:
    prompt: str
    model: str
    destinations: tuple[ChannelDestination, ...]
    title: str = "즉시 프롬프트"
    dry_run: bool = False


@dataclass(frozen=True)
class SendPromptResult:
    content: str
    successful_targets: tuple[str, ...]
    failed_targets: tuple[str, ...]


class SendPrompt:
    def __init__(
        self,
        openwebui: OpenWebUiPort,
        channel_resolver: ChannelResolver,
        clock: ClockPort,
    ) -> None:
        self._openwebui, self._channels, self._clock = openwebui, channel_resolver, clock

    def execute(self, command: SendPromptCommand) -> SendPromptResult:
        if not command.prompt.strip():
            raise ValueError("Prompt is required")
        if not command.model.strip():
            raise ValueError("Model is required")
        if not command.dry_run and not command.destinations:
            raise ValueError("At least one channel is required when dry run is disabled")
        logger.info(
            "event=instant_prompt_started model=%s dry_run=%s", command.model, command.dry_run
        )
        response = self._openwebui.generate(OpenWebUiRequest(command.model, command.prompt))
        if not response.content.strip():
            raise ValueError("Open WebUI returned empty content")
        if command.dry_run:
            logger.info(
                "event=instant_prompt_completed dry_run=true response_length=%s",
                len(response.content),
            )
            return SendPromptResult(response.content, (), ())
        successful: list[str] = []
        failed: list[str] = []
        message = OutboundMessage(command.title, response.content)
        for destination in command.destinations:
            target_label = f"{destination.channel_type}:{destination.target}"
            try:
                self._channels.resolve(destination.channel_type).send(destination.target, message)
                successful.append(target_label)
                logger.info(
                    "event=instant_delivery_success channel_type=%s target=%s",
                    destination.channel_type,
                    destination.target,
                )
            except Exception as error:
                failed.append(target_label)
                logger.warning(
                    "event=instant_delivery_failed channel_type=%s target=%s error_type=%s",
                    destination.channel_type,
                    destination.target,
                    type(error).__name__,
                )
        logger.info(
            "event=instant_prompt_completed dry_run=false successful=%s failed=%s",
            len(successful),
            len(failed),
        )
        return SendPromptResult(response.content, tuple(successful), tuple(failed))
