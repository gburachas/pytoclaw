"""Feishu (Lark) channel adapter — not yet implemented."""

from __future__ import annotations

import logging
from typing import Any

from pyclaw.bus.message_bus import MessageBus
from pyclaw.channels.base import BaseChannel
from pyclaw.models import OutboundMessage

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED_MSG = (
    "Feishu channel is not yet fully implemented. "
    "Incoming messages will not be received. "
    "See https://github.com/gburachas/pyclaw/issues for status."
)


class FeishuChannel(BaseChannel):
    """Feishu/Lark bot channel — stub awaiting SDK integration."""

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__("feishu", config, bus, getattr(config, "allow_from", []))
        self._app_id = getattr(config, "app_id", "")
        self._app_secret = getattr(config, "app_secret", "")

    async def start(self) -> None:
        logger.warning(_NOT_IMPLEMENTED_MSG)
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        logger.warning("Feishu send not implemented — message dropped: %s", msg.content[:50])
