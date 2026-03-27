"""Agent command — interactive chat and one-shot mode."""

from __future__ import annotations

import logging

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from pyclaw.agent.instance import AgentInstance
from pyclaw.agent.loop import AgentLoop
from pyclaw.bus.message_bus import MessageBus
from pyclaw.config import load_config
from pyclaw.config.models import AgentConfig
from pyclaw.providers.factory import create_provider
from pyclaw.tools.exec_tool import ExecTool
from pyclaw.tools.file_tools import (
    AppendFileTool,
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from pyclaw.tools.message_tool import EchoTool
from pyclaw.tools.spawn_tool import SpawnTool
from pyclaw.tools.web_tools import WebFetchTool, WebSearchTool

logger = logging.getLogger(__name__)
console = Console()


async def run_agent(
    message: str | None = None,
    config_path: str | None = None,
    model_override: str | None = None,
) -> None:
    """Run the agent in interactive or one-shot mode."""
    cfg = load_config(config_path)

    model_name = model_override or cfg.agents.defaults.model
    provider = create_provider(model_name, cfg)
    bus = MessageBus()
    loop = AgentLoop(cfg, bus, provider)

    # Register tools on the default agent
    agent = loop._registry.get_default_agent()
    _register_tools(agent, cfg)

    # Wire spawn tool's background handler to the agent loop
    spawn = agent.tools.get("spawn")
    if spawn and hasattr(spawn, "set_background_handler"):
        spawn.set_background_handler(loop.process_direct)

    if message:
        # One-shot mode
        response = await loop.process_direct(message)
        console.print(response)
        return

    # Interactive mode — enable streaming so tokens appear as they arrive
    import sys

    def _stream_to_console(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    loop.set_stream_callback(_stream_to_console)

    console.print(f"[bold]pyclaw[/bold] (model: {model_name})")
    console.print("Type your message. Use Ctrl+D or 'exit' to quit.\n")

    history_file = f"{cfg.config_dir}/cli_history"
    session: PromptSession[str] = PromptSession(history=FileHistory(history_file))

    while True:
        try:
            user_input = await session.prompt_async("you> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/quit"):
            console.print("Goodbye!")
            break

        # Handle slash commands
        if user_input.startswith("/"):
            _handle_slash(user_input, agent)
            continue

        sys.stdout.write(f"\n\033[32m{agent.name}>\033[0m ")
        response = await loop.process_direct(user_input)
        # If streaming was used, text was already printed; otherwise print it
        if not response or response == "(max iterations reached)":
            pass  # Already streamed or nothing to print
        sys.stdout.write("\n\n")
        sys.stdout.flush()


def _register_tools(agent: AgentInstance, cfg: "Config") -> None:
    """Register built-in tools on an agent."""
    ws = agent.workspace
    restrict = agent.restrict_to_workspace

    agent.tools.register(ReadFileTool(ws, restrict))
    agent.tools.register(WriteFileTool(ws, restrict))
    agent.tools.register(EditFileTool(ws, restrict))
    agent.tools.register(AppendFileTool(ws, restrict))
    agent.tools.register(ListDirTool(ws, restrict))
    agent.tools.register(ExecTool(
        ws, restrict,
        custom_deny_patterns=cfg.tools.exec.custom_deny_patterns,
        enable_deny_patterns=cfg.tools.exec.enable_deny_patterns,
    ))
    agent.tools.register(WebFetchTool())
    agent.tools.register(WebSearchTool(
        brave_api_key=cfg.tools.web.brave.api_key,
        tavily_api_key=cfg.tools.web.tavily.api_key,
    ))

    # Spawn tool
    spawn_tool = SpawnTool()
    agent.tools.register(spawn_tool)

    # Skill tools
    from pyclaw.skills.clawhub import ClawHubConfig, ClawHubRegistry
    from pyclaw.skills.creator import CreateSkillTool
    from pyclaw.skills.registry import RegistryManager
    from pyclaw.skills.search_cache import SearchCache
    from pyclaw.tools.skills_tools import FindSkillsTool, InstallSkillTool

    registry_mgr = RegistryManager()
    if cfg.tools.skills.hub_url:
        hub_cfg = ClawHubConfig(
            base_url=cfg.tools.skills.hub_url,
            auth_token=cfg.tools.skills.hub_auth_token,
        )
        registry_mgr.add_registry(ClawHubRegistry(hub_cfg))

    find_tool = FindSkillsTool(registry_mgr, SearchCache())
    install_tool = InstallSkillTool(ws, registry_mgr)
    create_tool = CreateSkillTool(ws, agent.skills_loader)

    agent.tools.register(find_tool)
    agent.tools.register(install_tool)
    agent.tools.register(create_tool)

    agent.context_builder.set_tools_registry(agent.tools)


def _handle_slash(command: str, agent: AgentInstance) -> None:
    """Handle in-chat slash commands."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/help":
        console.print("Available commands:")
        console.print("  /help     - Show this help")
        console.print("  /model    - Show current model")
        console.print("  /tools    - List available tools")
        console.print("  /clear    - Clear session history")
        console.print("  /exit     - Exit")
    elif cmd == "/model":
        console.print(f"Model: {agent.model}")
    elif cmd == "/tools":
        names = agent.tools.list_names()
        console.print(f"Tools ({len(names)}): {', '.join(names)}")
    elif cmd == "/clear":
        agent.sessions.clear("cli")
        console.print("Session cleared.")
    elif cmd in ("/exit", "/quit"):
        raise EOFError
    else:
        console.print(f"Unknown command: {cmd}")
