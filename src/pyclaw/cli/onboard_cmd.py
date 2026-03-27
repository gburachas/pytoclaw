"""Onboard command — first-run setup wizard."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table

from pyclaw.config.loader import load_config, save_config
from pyclaw.config.models import Config, ProviderConfig

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


def _mask_key(key: str) -> str:
    """Mask an API key for display, showing first 4 and last 4 chars."""
    if len(key) <= 10:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-5.3-codex",
        "anthropic": "anthropic/claude-sonnet-4-6",
        "ollama": "ollama/llama3",
        "openrouter": "openrouter/meta-llama/llama-3-70b",
    }.get(provider, "gpt-4o")


def _detect_current_provider(cfg: Config) -> str | None:
    """Detect which provider is currently configured."""
    if cfg.providers.openai.api_key or cfg.providers.openai.auth_method:
        return "openai"
    if cfg.providers.anthropic.api_key:
        return "anthropic"
    if cfg.providers.openrouter.api_key:
        return "openrouter"
    if cfg.providers.ollama.api_base:
        return "ollama"
    # Also check credential store for OAuth
    try:
        from pyclaw.auth.credentials import CredentialStore
        cred_store = CredentialStore()
        if cred_store.get("openai-codex"):
            return "openai"
    except Exception:
        pass
    return None



def run_onboard() -> None:
    """Interactive setup wizard for pyclaw."""
    console.print(Panel("[bold]Welcome to pyclaw![/bold]\n\nLet's set you up.", title="Setup Wizard"))

    config_dir = Path.home() / ".pyclaw"
    config_file = config_dir / "config.yaml"

    # ── Load existing config or start fresh ───────────────────────────
    is_rerun = config_file.exists()
    if is_rerun:
        action = Prompt.ask(
            "Config already exists. What would you like to do?",
            choices=["update", "reset"],
            default="update",
        )
        if action == "reset":
            cfg = Config()
            console.print("[dim]Starting fresh with default config.[/dim]")
        else:
            cfg = load_config()
            console.print("[dim]Loaded existing config — press Enter to keep current values.[/dim]")
    else:
        cfg = Config()

    # ── QuickStart vs Advanced ────────────────────────────────────────
    console.print()
    mode = Prompt.ask(
        "Setup mode",
        choices=["quickstart", "advanced"],
        default="quickstart",
    )
    is_advanced = mode == "advanced"

    if is_advanced:
        console.print("[dim]Advanced mode: identity, agent, provider, channels, web search.[/dim]")
    else:
        console.print("[dim]QuickStart: identity, agent, provider. Run again with 'advanced' for more.[/dim]")

    # ── Step 1: User Identity ─────────────────────────────────────────
    console.print("\n[bold cyan]Step 1: About you[/bold cyan]\n")

    user_name = Prompt.ask("What's your name?", default=cfg.user.name or "User")
    console.print("[dim]  Tell the agent about yourself — role, interests, expertise, anything.[/dim]")
    user_role = Prompt.ask("Describe yourself", default=cfg.user.role or "software engineer")
    user_address = Prompt.ask(
        "How should the agent address you?",
        default=cfg.user.address_as or user_name,
    )

    cfg.user.name = user_name
    cfg.user.role = user_role
    cfg.user.address_as = user_address

    # ── Step 2: Agent Personality ─────────────────────────────────────
    console.print("\n[bold cyan]Step 2: Your agent[/bold cyan]\n")

    agent_name = Prompt.ask("Name your agent", default=cfg.user.agent_name or "pyclaw")
    console.print("[dim]  Describe the personality you want — e.g. 'concise and technical', 'friendly mentor', etc.[/dim]")
    personality = Prompt.ask("Agent personality", default=cfg.user.personality or "concise and direct")
    console.print("[dim]  What will you use this agent for? Be as specific as you like.[/dim]")
    use_case = Prompt.ask("Primary use case", default=cfg.user.use_case or "coding")
    extra_instructions = Prompt.ask(
        "Any special instructions for the agent? (optional, Enter to skip)",
        default=cfg.user.extra_instructions or "",
    )

    cfg.user.agent_name = agent_name
    cfg.user.personality = personality
    cfg.user.use_case = use_case
    cfg.user.extra_instructions = extra_instructions

    # ── Step 3: LLM Provider ─────────────────────────────────────────
    console.print("\n[bold cyan]Step 3: LLM Provider[/bold cyan]\n")

    current_provider = _detect_current_provider(cfg)
    if current_provider:
        console.print(f"  [dim]Current provider: {current_provider}[/dim]")

    provider = Prompt.ask(
        "Primary LLM provider",
        choices=["openai", "anthropic", "ollama", "openrouter"],
        default=current_provider or "openai",
    )

    _setup_provider(cfg, provider, config_dir)

    default_model = _default_model(provider)
    current_model = cfg.agents.defaults.model
    valid = _VALID_MODELS.get(provider, [])
    if valid:
        console.print(f"  [dim]Known models: {', '.join(valid)}[/dim]")
    model = Prompt.ask("Default model", default=current_model if current_model != "gpt-4o" else default_model)

    if valid and model not in valid:
        console.print(f"[yellow]Note: '{model}' isn't in the known models list — using it anyway.[/yellow]")

    cfg.agents.defaults.model = model
    cfg.agents.defaults.provider = provider

    # ── Step 4: Channel Setup (Advanced only) ─────────────────────────
    if is_advanced:
        _step_channels(cfg)

    # ── Step 5: Web Search Config (Advanced only) ─────────────────────
    if is_advanced:
        _step_web_search(cfg)

    # ── Create workspace ──────────────────────────────────────────────
    workspace = Path(cfg.agents.defaults.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)
    (workspace / "sessions").mkdir(exist_ok=True)
    (workspace / "skills").mkdir(exist_ok=True)

    # Write identity files
    identity_content = _build_identity(agent_name, use_case)
    soul_content = _build_soul(personality, use_case)
    agent_content = _build_agent(use_case, extra_instructions)
    user_content = _build_user(user_name, user_address, user_role)

    if is_rerun:
        regen = Confirm.ask("Regenerate workspace files?", default=False)
        if regen:
            _write_file(workspace / "IDENTITY.md", identity_content)
            _write_file(workspace / "SOUL.md", soul_content)
            _write_file(workspace / "AGENT.md", agent_content)
            _write_file(workspace / "USER.md", user_content)
    else:
        _write_if_missing(workspace / "IDENTITY.md", identity_content)
        _write_if_missing(workspace / "SOUL.md", soul_content)
        _write_if_missing(workspace / "AGENT.md", agent_content)
        _write_if_missing(workspace / "USER.md", user_content)

    # Save config
    save_config(cfg)

    # ── Summary ───────────────────────────────────────────────────────
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
    console.print("\nRun [bold]pyclaw agent[/bold] to start chatting!")


# ── Provider setup ────────────────────────────────────────────────────

def _setup_provider(cfg: Config, provider: str, config_dir: Path) -> None:
    """Configure the selected LLM provider, preserving existing credentials."""
    if provider == "openai":
        _setup_openai(cfg, config_dir)
    elif provider == "ollama":
        existing_base = cfg.providers.ollama.api_base
        cfg.providers.ollama.api_base = existing_base or "http://localhost:11434/v1"
    elif provider == "anthropic":
        _setup_api_key_provider(cfg.providers.anthropic, "Anthropic")
    elif provider == "openrouter":
        _setup_api_key_provider(cfg.providers.openrouter, "OpenRouter")
        cfg.providers.openrouter.api_base = cfg.providers.openrouter.api_base or "https://openrouter.ai/api/v1"


def _setup_openai(cfg: Config, config_dir: Path) -> None:
    """Setup OpenAI provider with OAuth detection."""
    from pyclaw.auth.credentials import CredentialStore
    cred_store = CredentialStore(str(config_dir))

    # Detect existing auth
    existing_oauth = cred_store.get("openai-codex")
    has_oauth = existing_oauth is not None and existing_oauth.auth_type == "oauth"
    has_api_key = bool(cfg.providers.openai.api_key)

    # Show current status
    if has_oauth:
        console.print("  [dim]Current auth: OAuth (browser login)[/dim]")
    elif has_api_key:
        console.print(f"  [dim]Current auth: API key ({_mask_key(cfg.providers.openai.api_key)})[/dim]")

    # Default to existing method
    default_method = "browser_login" if has_oauth else ("api_key" if has_api_key else "browser_login")

    auth_method = Prompt.ask(
        "Authentication method",
        choices=["api_key", "browser_login"],
        default=default_method,
    )

    if auth_method == "browser_login":
        if has_oauth:
            keep = Confirm.ask("Keep existing OAuth credentials?", default=True)
            if keep:
                return
        console.print("\n[bold]Starting OpenAI OAuth login...[/bold]")
        console.print("[dim]This uses your ChatGPT Pro/Plus subscription (separate from API billing).[/dim]\n")
        import asyncio
        from pyclaw.auth.openai_oauth import login_openai_oauth
        oauth_creds = asyncio.get_event_loop().run_until_complete(login_openai_oauth())
        if oauth_creds:
            cred_store.store_oauth("openai-codex", oauth_creds)
            console.print("[green]OAuth login successful![/green]")
        else:
            console.print("[red]OAuth login failed. Falling back to API key.[/red]")
            _setup_api_key_provider(cfg.providers.openai, "OpenAI")
    else:
        if has_api_key:
            keep = Confirm.ask(
                f"Keep existing API key ({_mask_key(cfg.providers.openai.api_key)})?",
                default=True,
            )
            if keep:
                return
        api_key = Prompt.ask("OpenAI API key")
        cfg.providers.openai.api_key = api_key


def _setup_api_key_provider(provider_cfg: ProviderConfig, name: str) -> None:
    """Setup a provider that uses an API key, preserving existing keys."""
    if provider_cfg.api_key:
        keep = Confirm.ask(
            f"Keep existing {name} API key ({_mask_key(provider_cfg.api_key)})?",
            default=True,
        )
        if keep:
            return
    provider_cfg.api_key = Prompt.ask(f"{name} API key")


# ── Step 4: Channels ─────────────────────────────────────────────────

def _step_channels(cfg: Config) -> None:
    """Configure messaging channels."""
    console.print("\n[bold cyan]Step 4: Channel Setup[/bold cyan]\n")
    console.print("[dim]Configure messaging channels to connect your agent.[/dim]\n")

    _setup_telegram(cfg)
    _setup_whatsapp(cfg)
    _setup_discord(cfg)
    _setup_slack(cfg)


def _setup_telegram(cfg: Config) -> None:
    tg = cfg.channels.telegram
    status = "[green]enabled[/green]" if tg.enabled else "[dim]disabled[/dim]"
    token_status = f" (token: {_mask_key(tg.token)})" if tg.token else ""
    console.print(f"  Telegram: {status}{token_status}")

    enable = Confirm.ask("  Enable Telegram?", default=tg.enabled)
    tg.enabled = enable
    if not enable:
        return

    if tg.token:
        keep = Confirm.ask(f"  Keep existing token ({_mask_key(tg.token)})?", default=True)
        if not keep:
            tg.token = Prompt.ask("  Telegram bot token")
    else:
        tg.token = Prompt.ask("  Telegram bot token")

    existing_allow = ", ".join(tg.allow_from) if tg.allow_from else ""
    allow_input = Prompt.ask(
        "  Allowed user IDs (comma-separated, empty for all)",
        default=existing_allow,
    )
    tg.allow_from = [s.strip() for s in allow_input.split(",") if s.strip()] if allow_input else []


def _setup_whatsapp(cfg: Config) -> None:
    wa = cfg.channels.whatsapp
    status = "[green]enabled[/green]" if wa.enabled else "[dim]disabled[/dim]"
    console.print(f"  WhatsApp: {status}")

    enable = Confirm.ask("  Enable WhatsApp?", default=wa.enabled)
    wa.enabled = enable
    if not enable:
        return

    wa.bridge_url = Prompt.ask("  WhatsApp bridge URL", default=wa.bridge_url or "")
    existing_allow = ", ".join(wa.allow_from) if wa.allow_from else ""
    allow_input = Prompt.ask(
        "  Allowed phone numbers (comma-separated, empty for all)",
        default=existing_allow,
    )
    wa.allow_from = [s.strip() for s in allow_input.split(",") if s.strip()] if allow_input else []


def _setup_discord(cfg: Config) -> None:
    dc = cfg.channels.discord
    status = "[green]enabled[/green]" if dc.enabled else "[dim]disabled[/dim]"
    token_status = f" (token: {_mask_key(dc.token)})" if dc.token else ""
    console.print(f"  Discord: {status}{token_status}")

    enable = Confirm.ask("  Enable Discord?", default=dc.enabled)
    dc.enabled = enable
    if not enable:
        return

    if dc.token:
        keep = Confirm.ask(f"  Keep existing token ({_mask_key(dc.token)})?", default=True)
        if not keep:
            dc.token = Prompt.ask("  Discord bot token")
    else:
        dc.token = Prompt.ask("  Discord bot token")

    existing_allow = ", ".join(dc.allow_from) if dc.allow_from else ""
    allow_input = Prompt.ask(
        "  Allowed user IDs (comma-separated, empty for all)",
        default=existing_allow,
    )
    dc.allow_from = [s.strip() for s in allow_input.split(",") if s.strip()] if allow_input else []


def _setup_slack(cfg: Config) -> None:
    sl = cfg.channels.slack
    status = "[green]enabled[/green]" if sl.enabled else "[dim]disabled[/dim]"
    console.print(f"  Slack: {status}")

    enable = Confirm.ask("  Enable Slack?", default=sl.enabled)
    sl.enabled = enable
    if not enable:
        return

    if sl.bot_token:
        keep = Confirm.ask(f"  Keep existing bot token ({_mask_key(sl.bot_token)})?", default=True)
        if not keep:
            sl.bot_token = Prompt.ask("  Slack bot token (xoxb-...)")
    else:
        sl.bot_token = Prompt.ask("  Slack bot token (xoxb-...)")

    if sl.app_token:
        keep = Confirm.ask(f"  Keep existing app token ({_mask_key(sl.app_token)})?", default=True)
        if not keep:
            sl.app_token = Prompt.ask("  Slack app token (xapp-...)")
    else:
        sl.app_token = Prompt.ask("  Slack app token (xapp-...)")

    existing_allow = ", ".join(sl.allow_from) if sl.allow_from else ""
    allow_input = Prompt.ask(
        "  Allowed user IDs (comma-separated, empty for all)",
        default=existing_allow,
    )
    sl.allow_from = [s.strip() for s in allow_input.split(",") if s.strip()] if allow_input else []


# ── Step 5: Web Search ───────────────────────────────────────────────

def _step_web_search(cfg: Config) -> None:
    """Configure web search tools."""
    console.print("\n[bold cyan]Step 5: Web Search[/bold cyan]\n")
    console.print("[dim]Configure search providers. DuckDuckGo works without a key as fallback.[/dim]\n")

    # Brave
    brave_key = cfg.tools.web.brave.api_key
    if brave_key:
        console.print(f"  Brave Search: [green]configured[/green] ({_mask_key(brave_key)})")
        keep = Confirm.ask("  Keep existing Brave API key?", default=True)
        if not keep:
            cfg.tools.web.brave.api_key = Prompt.ask("  Brave Search API key (empty to clear)", default="")
    else:
        console.print("  Brave Search: [dim]not configured[/dim]")
        brave_input = Prompt.ask("  Brave Search API key (optional, Enter to skip)", default="")
        if brave_input:
            cfg.tools.web.brave.api_key = brave_input

    # Tavily
    tavily_key = cfg.tools.web.tavily.api_key
    if tavily_key:
        console.print(f"  Tavily: [green]configured[/green] ({_mask_key(tavily_key)})")
        keep = Confirm.ask("  Keep existing Tavily API key?", default=True)
        if not keep:
            cfg.tools.web.tavily.api_key = Prompt.ask("  Tavily API key (empty to clear)", default="")
    else:
        console.print("  Tavily: [dim]not configured[/dim] (alternative to Brave)")
        tavily_input = Prompt.ask("  Tavily API key (optional, Enter to skip)", default="")
        if tavily_input:
            cfg.tools.web.tavily.api_key = tavily_input

    # DuckDuckGo
    console.print(f"  DuckDuckGo: [green]always available[/green] (no key needed)")


# ── Workspace file builders ───────────────────────────────────────────

def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _build_identity(agent_name: str, use_case: str) -> str:
    return f"""# Identity

I am {agent_name}, a personal AI assistant built with pyclaw.
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
