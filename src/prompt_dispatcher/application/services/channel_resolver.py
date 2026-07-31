from collections.abc import Sequence

from prompt_dispatcher.application.ports.message_channel import MessageChannelPort
from prompt_dispatcher.domain.errors import UnsupportedChannelError


class ChannelResolver:
    def __init__(self, channels: Sequence[MessageChannelPort]) -> None:
        self._channels = {channel.channel_type: channel for channel in channels}

    def resolve(self, channel_type: str) -> MessageChannelPort:
        try:
            return self._channels[channel_type]
        except KeyError as exc:
            raise UnsupportedChannelError(f"Unsupported channel: {channel_type}") from exc

    @property
    def channel_types(self) -> set[str]:
        return set(self._channels)
