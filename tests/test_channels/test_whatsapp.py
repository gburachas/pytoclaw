"""Tests for WhatsApp channel features."""

import asyncio
import json

import pytest

from pyclaw.bus.message_bus import MessageBus
from pyclaw.channels.whatsapp import WhatsAppChannel
from pyclaw.config.models import WhatsAppConfig


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def config():
    return WhatsAppConfig(enabled=True, bridge_url="ws://localhost:9999")


# ---------------------------------------------------------------------------
# Message type filtering
# ---------------------------------------------------------------------------


class TestWhatsAppMessageFiltering:
    def test_handle_incoming_message_type_text(self, bus, config):
        """Only messages with type 'message' should be handled."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True

        # This should be processed
        ch._handle_incoming_message(
            {"type": "message", "from": "user1", "content": "hello"}
        )
        # The handle_message is fire-and-forget, so just check no crash

    def test_handle_incoming_missing_from(self, bus, config):
        """Messages without a 'from' field should be ignored."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        # Should not raise
        ch._handle_incoming_message({"type": "message", "content": "hello"})


# ---------------------------------------------------------------------------
# Media path extraction
# ---------------------------------------------------------------------------


class TestWhatsAppMedia:
    def test_media_paths_extracted(self, bus, config):
        """Media paths should be extracted from the 'media' field."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        # This exercises the code path — just verifying no crash and
        # the method accepts media data
        ch._handle_incoming_message(
            {
                "type": "message",
                "from": "user1",
                "content": "photo",
                "media": ["/tmp/photo.jpg", "/tmp/video.mp4"],
            }
        )


# ---------------------------------------------------------------------------
# Group vs direct detection
# ---------------------------------------------------------------------------


class TestWhatsAppPeerDetection:
    @pytest.mark.asyncio
    async def test_direct_message(self, bus, config):
        """When chat == from, peer_kind should be 'direct'."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        ch._handle_incoming_message(
            {"type": "message", "from": "user1", "content": "hi"}
        )
        # Give fire-and-forget task a chance to run
        await asyncio.sleep(0.05)
        msg = await bus.consume_inbound()
        assert msg is not None
        assert msg.metadata["peer_kind"] == "direct"
        assert msg.metadata["peer_id"] == "user1"

    @pytest.mark.asyncio
    async def test_group_message(self, bus, config):
        """When chat != from, peer_kind should be 'group'."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        ch._handle_incoming_message(
            {
                "type": "message",
                "from": "user1",
                "chat": "group123",
                "content": "hi",
            }
        )
        await asyncio.sleep(0.05)
        msg = await bus.consume_inbound()
        assert msg is not None
        assert msg.metadata["peer_kind"] == "group"
        assert msg.metadata["peer_id"] == "group123"


# ---------------------------------------------------------------------------
# from_name metadata
# ---------------------------------------------------------------------------


class TestWhatsAppMetadata:
    @pytest.mark.asyncio
    async def test_from_name_extracted(self, bus, config):
        """from_name should be stored as user_name in metadata."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        ch._handle_incoming_message(
            {
                "type": "message",
                "from": "user1",
                "from_name": "Alice",
                "content": "hi",
            }
        )
        await asyncio.sleep(0.05)
        msg = await bus.consume_inbound()
        assert msg is not None
        assert msg.metadata["user_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_message_id_extracted(self, bus, config):
        """Message id should be in metadata."""
        ch = WhatsAppChannel(config, bus)
        ch._running = True
        ch._handle_incoming_message(
            {
                "type": "message",
                "from": "user1",
                "id": "msg-42",
                "content": "hi",
            }
        )
        await asyncio.sleep(0.05)
        msg = await bus.consume_inbound()
        assert msg is not None
        assert msg.metadata["message_id"] == "msg-42"


# ---------------------------------------------------------------------------
# Send with mutex
# ---------------------------------------------------------------------------


class TestWhatsAppSend:
    @pytest.mark.asyncio
    async def test_send_no_connection_raises(self, bus, config):
        """send() should raise RuntimeError when not connected."""
        ch = WhatsAppChannel(config, bus)
        with pytest.raises(RuntimeError, match="not established"):
            await ch.send(
                __import__("pyclaw.models", fromlist=["OutboundMessage"]).OutboundMessage(
                    channel="whatsapp", chat_id="user1", content="hello"
                )
            )
