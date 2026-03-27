"""WhatsApp channel adapter via WebSocket bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pyclaw.bus.message_bus import MessageBus
from pyclaw.channels.base import BaseChannel
from pyclaw.models import OutboundMessage

logger = logging.getLogger(__name__)


class WhatsAppChannel(BaseChannel):
    """WhatsApp channel via WebSocket bridge."""

    def __init__(self, config: Any, bus: MessageBus):
        allow_from = getattr(config, "allow_from", []) or []
        super().__init__("whatsapp", config, bus, allow_from)
        self._url = config.bridge_url
        self._ws: Any = None
        self._task: asyncio.Task | None = None
        self._mu = asyncio.Lock()
        self._connected = False

    async def start(self) -> None:
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets is required. Install with: pip install websockets"
            )

        logger.info("Starting WhatsApp channel connecting to %s...", self._url)

        ws = await websockets.connect(self._url, open_timeout=10)

        async with self._mu:
            self._ws = ws
            self._connected = True

        self._running = True
        logger.info("WhatsApp channel connected")
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        logger.info("Stopping WhatsApp channel...")

        async with self._mu:
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    logger.exception("Error closing WhatsApp connection")
                self._ws = None
            self._connected = False

        self._running = False

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send(self, msg: OutboundMessage) -> None:
        async with self._mu:
            if self._ws is None:
                raise RuntimeError("whatsapp connection not established")

            payload = json.dumps({
                "type": "message",
                "to": msg.chat_id,
                "content": msg.content,
            })
            await self._ws.send(payload)

    async def _listen(self) -> None:
        while self._running:
            try:
                async with self._mu:
                    ws = self._ws

                if ws is None:
                    await asyncio.sleep(1)
                    continue

                async for raw in ws:
                    if not self._running:
                        return

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Failed to unmarshal WhatsApp message")
                        continue

                    msg_type = data.get("type")
                    if msg_type != "message":
                        continue

                    self._handle_incoming_message(data)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WhatsApp read error")
                await asyncio.sleep(2)

    def _handle_incoming_message(self, msg: dict[str, Any]) -> None:
        sender_id = msg.get("from")
        if not isinstance(sender_id, str) or not sender_id:
            return

        chat_id = msg.get("chat")
        if not isinstance(chat_id, str) or not chat_id:
            chat_id = sender_id

        content = msg.get("content", "")
        if not isinstance(content, str):
            content = ""

        # Extract media paths
        media_paths: list[str] = []
        media_data = msg.get("media")
        if isinstance(media_data, list):
            for m in media_data:
                if isinstance(m, str):
                    media_paths.append(m)

        # Build metadata
        metadata: dict[str, str] = {}

        message_id = msg.get("id")
        if isinstance(message_id, str):
            metadata["message_id"] = message_id

        user_name = msg.get("from_name")
        if isinstance(user_name, str):
            metadata["user_name"] = user_name

        # Group vs direct peer detection
        if chat_id == sender_id:
            metadata["peer_kind"] = "direct"
            metadata["peer_id"] = sender_id
        else:
            metadata["peer_kind"] = "group"
            metadata["peer_id"] = chat_id

        truncated = content[:50] if len(content) > 50 else content
        logger.info("WhatsApp message from %s: %s...", sender_id, truncated)

        # Fire-and-forget the async handle_message call
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.handle_message(sender_id, chat_id, content, media=media_paths, metadata=metadata)
            )
        except RuntimeError:
            # No running loop (e.g. in tests) — run synchronously
            asyncio.ensure_future(
                self.handle_message(sender_id, chat_id, content, media=media_paths, metadata=metadata)
            )
