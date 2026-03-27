"""Gateway command — multi-channel server mode."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from rich.console import Console

from pyclaw import __version__

logger = logging.getLogger(__name__)
console = Console()


async def run_gateway(config_path: str | None = None) -> None:
    """Start the multi-channel gateway server."""
    from pyclaw.agent.loop import AgentLoop
    from pyclaw.bus.message_bus import MessageBus
    from pyclaw.channels.base import ChannelManager
    from pyclaw.cli.agent_cmd import _register_tools
    from pyclaw.config import load_config
    from pyclaw.providers.factory import create_provider
    from pyclaw.services.cron_service import CronService
    from pyclaw.services.heartbeat import HeartbeatService

    cfg = load_config(config_path)

    console.print(f"[bold]pyclaw gateway[/bold] v{__version__}")

    # 1. Create provider
    model_name = cfg.agents.defaults.model
    provider = create_provider(model_name, cfg)
    console.print(f"  Model: {model_name}")

    # 2. Create MessageBus
    bus = MessageBus()

    # 3. Create AgentLoop
    loop = AgentLoop(cfg, bus, provider)
    agent = loop._registry.get_default_agent()
    _register_tools(agent, cfg)

    # 4. Initialize channels
    channel_mgr = ChannelManager(bus)
    _init_channels(cfg, bus, channel_mgr)

    # 5. Create services
    workspace = cfg.agents.defaults.workspace

    cron_svc = CronService(f"{workspace}/cron")
    heartbeat_svc = HeartbeatService(
        workspace=workspace,
        interval_minutes=cfg.heartbeat.interval,
        enabled=cfg.heartbeat.enabled,
    )

    # 6. Start everything
    await channel_mgr.start_all()
    enabled = channel_mgr.get_enabled_channels()
    console.print(f"  Channels: {', '.join(enabled) if enabled else 'none'}")

    if cfg.heartbeat.enabled:
        heartbeat_svc.start()
        console.print(f"  Heartbeat: every {cfg.heartbeat.interval}m")

    cron_svc.start()
    console.print("  Cron service: started")

    # 7. Start health endpoint
    health_task = asyncio.create_task(
        _start_health_server(cfg.gateway.host, cfg.gateway.port)
    )
    console.print(f"  Health: http://{cfg.gateway.host}:{cfg.gateway.port}/health")

    # 8. Start outbound dispatcher
    dispatch_task = asyncio.create_task(_dispatch_outbound(bus, channel_mgr))

    console.print("\n[green]Gateway running. Press Ctrl+C to stop.[/green]\n")

    # 9. Run agent loop
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()
        loop.stop()

    aio_loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        aio_loop.add_signal_handler(sig, _signal_handler)

    agent_task = asyncio.create_task(loop.run())

    await stop_event.wait()

    # Graceful shutdown
    console.print("\n[yellow]Shutting down...[/yellow]")
    heartbeat_svc.stop()
    cron_svc.stop()
    await channel_mgr.stop_all()
    health_task.cancel()
    dispatch_task.cancel()
    agent_task.cancel()
    console.print("[green]Shutdown complete.[/green]")


def _init_channels(cfg: Any, bus: "MessageBus", mgr: "ChannelManager") -> None:
    """Initialize enabled channels from config."""
    if cfg.channels.telegram.enabled and cfg.channels.telegram.token:
        from pyclaw.channels.telegram import TelegramChannel
        mgr.add_channel(TelegramChannel(cfg.channels.telegram, bus))

    if cfg.channels.discord.enabled and cfg.channels.discord.token:
        from pyclaw.channels.discord_ch import DiscordChannel
        mgr.add_channel(DiscordChannel(cfg.channels.discord, bus))

    if cfg.channels.slack.enabled and cfg.channels.slack.bot_token:
        from pyclaw.channels.slack_ch import SlackChannel
        mgr.add_channel(SlackChannel(cfg.channels.slack, bus))

    if cfg.channels.whatsapp.enabled and cfg.channels.whatsapp.bridge_url:
        from pyclaw.channels.whatsapp import WhatsAppChannel
        mgr.add_channel(WhatsAppChannel(cfg.channels.whatsapp, bus))


async def _dispatch_outbound(bus: "MessageBus", mgr: "ChannelManager") -> None:
    """Route outbound messages to the correct channel."""
    while True:
        msg = await bus.consume_outbound()
        if msg is None:
            continue
        await mgr.send_to_channel(msg.channel, msg.chat_id, msg.content)


async def _start_health_server(host: str, port: int) -> None:
    """Start a minimal health check HTTP server."""
    from aiohttp import web

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "version": __version__})

    async def ready(request: web.Request) -> web.Response:
        return web.json_response({"status": "ready"})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Keep running
    while True:
        await asyncio.sleep(3600)
