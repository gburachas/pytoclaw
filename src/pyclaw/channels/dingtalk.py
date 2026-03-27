"""DingTalk channel adapter — not yet implemented."""

from __future__ import annotations

import logging
from typing import Any

from pyclaw.bus.message_bus import MessageBus
from pyclaw.channels.base import BaseChannel
from pyclaw.models import OutboundMessage

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED_MSG = (
    "DingTalk channel is not yet fully implemented. "
    "Incoming messages will not be received. "
    "See https://github.com/gburachas/pyclaw/issues for status."
)


class DingTalkChannel(BaseChannel):
    """DingTalk bot channel — stub awaiting Stream SDK integration."""

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__("dingtalk", config, bus, getattr(config, "allow_from", []))
        self._client_id = getattr(config, "client_id", "")
        self._client_secret = getattr(config, "client_secret", "")

    async def start(self) -> None:
        logger.warning(_NOT_IMPLEMENTED_MSG)
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        logger.warning("DingTalk send not implemented — message dropped: %s", msg.content[:50])
