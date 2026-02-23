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
    user_role = Prompt.ask(
        "What do you primarily do?",
        choices=["software engineer", "researcher", "student", "creative", "other"],
        default="software engineer",
    )
    user_address = Prompt.ask(
        "How should the agent address you?",
        default=user_name,
    )

    # ── Step 2: Agent personality ──────────────────────────────────────
    console.print("\n[bold cyan]Step 2: Agent personality[/bold cyan]\n")

    agent_name = Prompt.ask("Name your agent", default="pytoclaw")
    personality = Prompt.ask(
        "Agent personality style",
        choices=["concise", "friendly", "professional", "playful"],
        default="concise",
    )
    use_case = Prompt.ask(
        "Primary use case",
        choices=["coding", "research", "writing", "general assistant", "devops"],
        default="coding",
    )
    extra_instructions = Prompt.ask(
        "Any special instructions for the agent? (optional, press Enter to skip)",
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
    if provider != "ollama":
        api_key = Prompt.ask(f"{provider.title()} API key")

    default_model = _default_model(provider)
    valid = _VALID_MODELS.get(provider, [])
    if valid:
        console.print(f"  Available models: {', '.join(valid)}")
    model = Prompt.ask("Default model", default=default_model)

    # Validate model name
    if provider == "openai" and model not in valid:
        console.print(f"[yellow]Warning: '{model}' may not be a valid OpenAI model.[/yellow]")
        console.print(f"  Known models: {', '.join(valid)}")
        confirm = Prompt.ask("Use it anyway?", choices=["y", "n"], default="n")
        if confirm != "y":
            model = default_model
            console.print(f"  Using default: {model}")

    # ── Build config ───────────────────────────────────────────────────
    cfg = Config()
    cfg.agents.defaults.model = model

    if provider == "openai":
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
        f"[green]Agent name:[/green]    {agent_name}\n"
        f"[green]Personality:[/green]   {personality}\n"
        f"[green]Use case:[/green]      {use_case}\n"
        f"[green]Model:[/green]         {model}\n"
        f"[green]User:[/green]          {user_name} ({user_role})",
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
Primary role: {use_case} assistant
"""


def _build_soul(personality: str, use_case: str) -> str:
    traits = {
        "concise": "I am concise and direct. I get to the point quickly without unnecessary preamble. I value clarity and efficiency in communication.",
        "friendly": "I am warm and approachable. I communicate in a friendly, conversational tone while staying helpful and informative.",
        "professional": "I am professional and thorough. I provide well-structured, detailed responses and maintain a formal but approachable tone.",
        "playful": "I am creative and lighthearted. I bring energy to conversations while staying helpful and accurate.",
    }
    use_case_notes = {
        "coding": "I excel at writing clean, correct code. I read before I edit, I explain my reasoning, and I test my work.",
        "research": "I excel at finding, synthesizing, and presenting information. I cite sources and distinguish facts from opinions.",
        "writing": "I excel at crafting clear, engaging text. I adapt my writing style to the context and audience.",
        "general assistant": "I am versatile and adaptable. I handle a wide range of tasks from scheduling to analysis to creative work.",
        "devops": "I excel at infrastructure, automation, and operational tasks. I prioritize reliability and security.",
    }
    return f"""# Soul

{traits.get(personality, traits['concise'])}

{use_case_notes.get(use_case, '')}
"""


def _build_agent(use_case: str, extra_instructions: str) -> str:
    base = """# Agent Instructions

- Use tools to accomplish tasks rather than just describing what to do.
- Read files before modifying them.
- Be concise in responses.
- Remember important facts in MEMORY.md.
"""
    use_case_extras = {
        "coding": "- Prefer editing existing files over creating new ones.\n- Run tests after making changes.\n- Follow the project's existing style and conventions.\n",
        "research": "- Search the web for current information.\n- Cross-reference multiple sources.\n- Note the date and source of information.\n",
        "writing": "- Ask for clarification on tone and audience.\n- Offer revisions rather than rewriting from scratch.\n",
        "devops": "- Always check current state before making changes.\n- Prefer non-destructive operations.\n- Back up configurations before modifying them.\n",
    }
    result = base + use_case_extras.get(use_case, "")
    if extra_instructions:
        result += f"\n## Custom Instructions\n\n{extra_instructions}\n"
    return result


def _build_user(user_name: str, address_as: str, role: str) -> str:
    return f"""# User Profile

Name: {user_name}
Address as: {address_as}
Role: {role}
"""
