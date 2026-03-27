# pyclaw

[![PyPI version](https://img.shields.io/pypi/v/pyclaw.svg)](https://pypi.org/project/pyclaw/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Ultra-lightweight personal AI assistant — Python port of [PicoClaw](https://github.com/sipeed/picoclaw).

## Features

- **Multi-provider LLM**: OpenAI, Anthropic Claude, Groq, Ollama, DeepSeek, OpenRouter, and more
- **Streaming output**: Real-time token streaming in interactive CLI mode
- **Fallback chains**: Automatic failover between providers with cooldown tracking
- **20+ built-in tools**: File I/O, shell execution, web search/fetch, cron scheduling, subagent spawning, hardware I2C/SPI
- **Multi-channel**: Telegram, Discord, Slack, WhatsApp, LINE, DingTalk, Feishu, WeCom, OneBot/QQ, MaixCAM
- **4-tier skill system**: Workspace → project → global → builtin skill loading with progressive disclosure
- **Skills marketplace**: Search and install skills from ClawHub or GitHub
- **Persistent memory**: Long-term (MEMORY.md) + daily notes + session-based conversation history
- **Multi-agent**: Multiple agents with workspace isolation, route-based dispatching
- **Background tasks**: Spawn subagents for long-running work with async result delivery
- **Services**: Heartbeat monitoring, cron job scheduling, USB device detection
- **Sandboxed execution**: 30+ dangerous command deny patterns for safe shell access
- **Fully typed**: PEP 561 `py.typed` marker included

## Installation

```bash
pip install pyclaw
```

### With channel support

```bash
# Telegram only
pip install pyclaw[telegram]

# Discord only
pip install pyclaw[discord]

# Slack only
pip install pyclaw[slack]

# All channels
pip install pyclaw[telegram,discord,slack]
```

### From source (development)

```bash
git clone https://github.com/gburachas/pyclaw.git
cd pyclaw
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,telegram,discord,slack]"
```

## Quick Start

```bash
# First-time setup — creates workspace, configures provider
pyclaw onboard

# Interactive chat (with streaming)
pyclaw agent

# One-shot mode
pyclaw agent "What files are in the current directory?"

# Start multi-channel gateway
pyclaw gateway
```

## Configuration

pyclaw uses YAML configuration. Default location: `~/.pyclaw/config.yaml`

```yaml
providers:
  default: "anthropic/claude-sonnet-4-20250514"
  list:
    - name: anthropic
      kind: anthropic
      api_key_env: ANTHROPIC_API_KEY
    - name: openai
      kind: openai
      api_key_env: OPENAI_API_KEY

agents:
  default: main
  list:
    - name: main
      model: "anthropic/claude-sonnet-4-20250514"
      workspace: ~/.pyclaw/workspace

channels:
  telegram:
    enabled: true
    token_env: TELEGRAM_BOT_TOKEN

tools:
  exec:
    enabled: true
    timeout_seconds: 30
    deny_enabled: true
  skills:
    hub_url: ""  # Optional: ClawHub registry URL
```

## Skills

pyclaw uses a 4-tier skill system. Skills are Markdown files (`SKILL.md`) with YAML frontmatter that extend the agent's capabilities.

### Skill tiers (highest priority first)

| Tier | Location | Use case |
|------|----------|----------|
| **Workspace** | `<workspace>/skills/<name>/SKILL.md` | Per-workspace customization |
| **Project** | `.agents/skills/<name>/SKILL.md` | Shared via version control |
| **Global** | `~/.pyclaw/skills/<name>/SKILL.md` | User-wide skills |
| **Builtin** | Bundled with pyclaw | Always available (weather, calculator, skill-creator) |

Higher tiers shadow lower tiers with the same name.

### Managing skills

```bash
# List all skills across tiers
pyclaw skills list

# Search ClawHub registry
pyclaw skills search "code review"

# Install from GitHub
pyclaw skills install user/repo

# Show a specific skill
pyclaw skills show my-skill
```

The agent can also create new skills via the `create_skill` tool, with automatic synergy analysis of existing skills.

## CLI Commands

| Command | Description |
|---------|-------------|
| `pyclaw onboard` | First-run setup wizard |
| `pyclaw agent [MESSAGE]` | Interactive chat or one-shot mode |
| `pyclaw gateway` | Start multi-channel gateway server |
| `pyclaw status` | Show agent/provider status |
| `pyclaw version` | Show version |
| `pyclaw auth login` | Add provider credentials |
| `pyclaw auth logout` | Remove provider credentials |
| `pyclaw cron list` | List scheduled jobs |
| `pyclaw cron add` | Add a cron job |
| `pyclaw skills list` | List skills across all tiers |
| `pyclaw skills search` | Search skill registries |
| `pyclaw skills install` | Install a skill |

### In-Chat Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/model` | Show current model |
| `/tools` | List available tools |
| `/clear` | Clear conversation history |

## Architecture

```
┌─────────────────────────────────────────────┐
│                    CLI / Gateway              │
├───────────┬───────────┬───────────┬──────────┤
│ Telegram  │ Discord   │ Slack     │ ...      │  ← Channels
├───────────┴───────────┴───────────┴──────────┤
│              Message Bus (asyncio.Queue)       │
├──────────────────────────────────────────────┤
│              Agent Loop (streaming + fallback) │
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ Context   │ │ Session   │ │ Memory      │ │
│  │ Builder   │ │ Manager   │ │ Store       │ │
│  └──────────┘ └───────────┘ └─────────────┘ │
├──────────────────────────────────────────────┤
│  Provider Layer (Fallback Chain)              │
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ Anthropic │ │ OpenAI    │ │ Ollama/etc  │ │
│  └──────────┘ └───────────┘ └─────────────┘ │
├──────────────────────────────────────────────┤
│  Tool Registry                                │
│  file │ exec │ web │ cron │ spawn │ skills   │
├──────────────────────────────────────────────┤
│  Skills (4-tier: workspace/project/global/    │
│          builtin + ClawHub + GitHub)           │
├──────────────────────────────────────────────┤
│  Services: Heartbeat │ Cron │ Device Monitor  │
└──────────────────────────────────────────────┘
```

## Development

```bash
# Install with all dev + channel dependencies
pip install -e ".[dev,telegram,discord,slack]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=pyclaw

# Lint
ruff check src/

# Type check
mypy src/pyclaw/
```

## Project Structure

```
src/pyclaw/
├── models.py              # Core Pydantic data models
├── protocols.py           # Abstract interfaces (LLMProvider, Tool, Channel)
├── config/                # YAML/JSON config loading
├── providers/             # LLM provider adapters + fallback chain + streaming
├── tools/                 # Built-in tools (file, exec, web, cron, spawn, skills)
├── agent/                 # Agent loop, registry, context builder
├── session/               # Session persistence
├── memory/                # Long-term + daily memory store
├── skills/                # 4-tier loader, registry, ClawHub, GitHub, creator
│   └── builtins/          # Bundled skills (weather, calculator, skill-creator)
├── bus/                   # Async message bus
├── routing/               # Multi-agent route resolver
├── channels/              # Chat platform adapters
├── services/              # Background services (heartbeat, cron, devices)
└── cli/                   # Typer CLI commands
```

## Requirements

- Python 3.11+
- An LLM API key (Anthropic, OpenAI, or compatible provider)

## License

MIT
