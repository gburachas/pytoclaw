"""Onboard command — first-run setup wizard."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel

from pytoclaw.config.loader import save_config
from pytoclaw.config.models import Config, ProviderConfig

console = Console()

_VALID_MODELS = {
    "openai": ["gpt-5.3-codex", "gpt-5.3-codex-spark", "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o3-mini", "o4-mini"],
    "anthropic": [
        "anthropic/claude-opus-4-6",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-haiku-4-5",
    ],
    "ollama": ["ollama/llama3", "ollama/llama3:70b", "ollama/mistral", "ollama/codellama"],
    "openrouter": [
        "openrouter/anthropic/claude-sonnet-4-6",
        "openrouter/meta-llama/llama-3-70b",
    ],
}


def run_onboard() -> None:
    """Interactive setup wizard for pytoclaw."""
    console.print(Panel("[bold]Welcome to pytoclaw![/bold]\n\nLet's set you up.", title="Setup Wizard"))

    config_dir = Path.home() / ".pytoclaw"
    config_file = config_dir / "config.yaml"

    if config_file.exists():
        overwrite = Prompt.ask(
            "Config already exists. Overwrite?", choices=["y", "n"], default="n"
        )
        if overwrite != "y":
            console.print("Setup cancelled.")
            return

    # ── Step 1: User identity ──────────────────────────────────────────
    console.print("\n[bold cyan]Step 1: About you[/bold cyan]\n")

    user_name = Prompt.ask("What's your name?", default="User")
    console.print("[dim]  Tell the agent about yourself — role, interests, expertise, anything.[/dim]")
    user_role = Prompt.ask("Describe yourself", default="software engineer")
    user_address = Prompt.ask(
        "How should the agent address you?",
        default=user_name,
    )

    # ── Step 2: Agent personality ──────────────────────────────────────
    console.print("\n[bold cyan]Step 2: Your agent[/bold cyan]\n")

    agent_name = Prompt.ask("Name your agent", default="pytoclaw")
    console.print("[dim]  Describe the personality you want — e.g. 'concise and technical', 'friendly mentor', etc.[/dim]")
    personality = Prompt.ask("Agent personality", default="concise and direct")
    console.print("[dim]  What will you use this agent for? Be as specific as you like.[/dim]")
    use_case = Prompt.ask("Primary use case", default="coding")
    extra_instructions = Prompt.ask(
        "Any special instructions for the agent? (optional, Enter to skip)",
        default="",
    )

    # ── Step 3: Provider setup ─────────────────────────────────────────
    console.print("\n[bold cyan]Step 3: LLM Provider[/bold cyan]\n")

    provider = Prompt.ask(
        "Primary LLM provider",
        choices=["openai", "anthropic", "ollama", "openrouter"],
        default="openai",
    )

    api_key = ""
    oauth_creds = None
    if provider == "openai":
        auth_method = Prompt.ask(
            "Authentication method",
            choices=["api_key", "browser_login"],
            default="browser_login",
        )
        if auth_method == "browser_login":
            console.print("\n[bold]Starting OpenAI OAuth login...[/bold]")
            console.print("[dim]This uses your ChatGPT Pro/Plus subscription (separate from API billing).[/dim]\n")
            import asyncio
            from pytoclaw.auth.openai_oauth import login_openai_oauth
            oauth_creds = asyncio.get_event_loop().run_until_complete(login_openai_oauth())
            if oauth_creds:
                console.print("[green]OAuth login successful![/green]")
            else:
                console.print("[red]OAuth login failed. Falling back to API key.[/red]")
                api_key = Prompt.ask("OpenAI API key")
        else:
            api_key = Prompt.ask("OpenAI API key")
    elif provider != "ollama":
        api_key = Prompt.ask(f"{provider.title()} API key")

    default_model = _default_model(provider)
    valid = _VALID_MODELS.get(provider, [])
    if valid:
        console.print(f"  [dim]Known models: {', '.join(valid)}[/dim]")
    model = Prompt.ask("Default model", default=default_model)

    # Warn on unknown model but don't block
    if valid and model not in valid:
        console.print(f"[yellow]Note: '{model}' isn't in the known models list — using it anyway.[/yellow]")

    # ── Build config ───────────────────────────────────────────────────
    cfg = Config()
    cfg.agents.defaults.model = model

    if provider == "openai":
        if oauth_creds:
            # Store OAuth credentials securely
            from pytoclaw.auth.credentials import CredentialStore
            cred_store = CredentialStore(str(config_dir))
            cred_store.store_oauth("openai-codex", oauth_creds)
            # Don't store API key in config — it comes from OAuth
        else:
            cfg.providers.openai.api_key = api_key
    elif provider == "anthropic":
        cfg.providers.anthropic.api_key = api_key
    elif provider == "openrouter":
        cfg.providers.openrouter.api_key = api_key
        cfg.providers.openrouter.api_base = "https://openrouter.ai/api/v1"
    elif provider == "ollama":
        cfg.providers.ollama.api_base = "http://localhost:11434/v1"

    # ── Create workspace ───────────────────────────────────────────────
    workspace = Path(cfg.agents.defaults.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)
    (workspace / "sessions").mkdir(exist_ok=True)
    (workspace / "skills").mkdir(exist_ok=True)

    # Write identity files with personalization
    identity_content = _build_identity(agent_name, use_case)
    soul_content = _build_soul(personality, use_case)
    agent_content = _build_agent(use_case, extra_instructions)
    user_content = _build_user(user_name, user_address, user_role)

    _write_if_missing(workspace / "IDENTITY.md", identity_content)
    _write_if_missing(workspace / "SOUL.md", soul_content)
    _write_if_missing(workspace / "AGENT.md", agent_content)
    _write_if_missing(workspace / "USER.md", user_content)

    # Save config
    save_config(cfg)

    # ── Summary ────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[green]Config saved:[/green]  {config_file}\n"
        f"[green]Workspace:[/green]     {workspace}\n"
        f"[green]Agent:[/green]         {agent_name} — {personality}\n"
        f"[green]Use case:[/green]      {use_case}\n"
        f"[green]Model:[/green]         {model}\n"
        f"[green]User:[/green]          {user_name} — {user_role}",
        title="Setup Complete",
    ))
    console.print("\nRun [bold]pytoclaw agent[/bold] to start chatting!")


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-5.3-codex",
        "anthropic": "anthropic/claude-sonnet-4-6",
        "ollama": "ollama/llama3",
        "openrouter": "openrouter/meta-llama/llama-3-70b",
    }.get(provider, "gpt-4o")


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _build_identity(agent_name: str, use_case: str) -> str:
    return f"""# Identity

I am {agent_name}, a personal AI assistant built with pytoclaw.
Version: 0.1.0
Primary focus: {use_case}
"""


def _build_soul(personality: str, use_case: str) -> str:
    return f"""# Soul

{personality}

I focus on: {use_case}
"""


def _build_agent(use_case: str, extra_instructions: str) -> str:
    result = f"""# Agent Instructions

Primary focus: {use_case}

- Use tools to accomplish tasks rather than just describing what to do.
- Read files before modifying them.
- Be concise in responses.
- Remember important facts in MEMORY.md.
"""
    if extra_instructions:
        result += f"\n## Custom Instructions\n\n{extra_instructions}\n"
    return result


def _build_user(user_name: str, address_as: str, role: str) -> str:
    return f"""# User Profile

Name: {user_name}
Address as: {address_as}
About: {role}
"""
