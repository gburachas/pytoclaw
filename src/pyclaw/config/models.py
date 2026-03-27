"""Configuration data models for pyclaw."""

from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class AgentModelConfig(BaseModel):
    primary: str = ""
    fallbacks: list[str] = Field(default_factory=list)


class SubagentsConfig(BaseModel):
    allow_agents: list[str] = Field(default_factory=list)
    model: Optional[AgentModelConfig] = None


class AgentConfig(BaseModel):
    id: str = ""
    default: bool = False
    name: str = ""
    workspace: str = ""
    model: Optional[AgentModelConfig] = None
    skills: list[str] = Field(default_factory=list)
    subagents: Optional[SubagentsConfig] = None


class AgentDefaults(BaseModel):
    workspace: str = "~/.pyclaw/workspace"
    restrict_to_workspace: bool = True
    provider: str = ""
    model: str = "gpt-4o"
    model_fallbacks: list[str] = Field(default_factory=list)
    image_model: str = ""
    image_model_fallbacks: list[str] = Field(default_factory=list)
    max_tokens: int = 8192
    temperature: Optional[float] = 0.7
    max_tool_iterations: int = 20


class AgentsConfig(BaseModel):
    model_config = {"populate_by_name": True}

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    agents: List[AgentConfig] = Field(default_factory=list, alias="list")


class PeerMatch(BaseModel):
    kind: str = ""  # "direct", "group", "channel"
    id: str = ""


class BindingMatch(BaseModel):
    channel: str = ""
    account_id: str = ""
    peer: Optional[PeerMatch] = None
    guild_id: str = ""
    team_id: str = ""


class AgentBinding(BaseModel):
    agent_id: str = ""
    match: BindingMatch = Field(default_factory=BindingMatch)


class SessionConfig(BaseModel):
    dm_scope: str = "main"
    identity_links: dict[str, list[str]] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    api_key: str = ""
    api_base: str = ""
    proxy: str = ""
    auth_method: str = ""
    connect_mode: str = ""


class OpenAIProviderConfig(ProviderConfig):
    web_search: bool = False


class ProvidersConfig(BaseModel):
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: OpenAIProviderConfig = Field(default_factory=OpenAIProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    qwen: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)
    cerebras: ProviderConfig = Field(default_factory=ProviderConfig)


class ModelConfig(BaseModel):
    model_name: str = ""
    model: str = ""
    api_base: str = ""
    api_key: str = ""
    proxy: str = ""
    auth_method: str = ""
    connect_mode: str = ""
    workspace: str = ""
    rpm: int = 0
    max_tokens_field: str = ""


class TelegramConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    proxy: str = ""
    allow_from: list[str] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    mention_only: bool = False


class SlackConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    app_token: str = ""
    allow_from: list[str] = Field(default_factory=list)


class WhatsAppConfig(BaseModel):
    enabled: bool = False
    bridge_url: str = ""
    allow_from: list[str] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)


class BraveConfig(BaseModel):
    api_key: str = ""


class TavilyConfig(BaseModel):
    api_key: str = ""


class DuckDuckGoConfig(BaseModel):
    enabled: bool = True


class WebToolsConfig(BaseModel):
    brave: BraveConfig = Field(default_factory=BraveConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    duckduckgo: DuckDuckGoConfig = Field(default_factory=DuckDuckGoConfig)


class ExecConfig(BaseModel):
    enable_deny_patterns: bool = True
    custom_deny_patterns: list[str] = Field(default_factory=list)


class CronToolsConfig(BaseModel):
    exec_timeout_minutes: int = 5


class SkillsToolsConfig(BaseModel):
    hub_url: str = ""
    hub_auth_token: str = ""
    github_enabled: bool = True


class ToolsConfig(BaseModel):
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    cron: CronToolsConfig = Field(default_factory=CronToolsConfig)
    exec: ExecConfig = Field(default_factory=ExecConfig)
    skills: SkillsToolsConfig = Field(default_factory=SkillsToolsConfig)


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class HeartbeatConfig(BaseModel):
    enabled: bool = False
    interval: int = 30  # minutes


class DevicesConfig(BaseModel):
    enabled: bool = False
    monitor_usb: bool = False


class UserConfig(BaseModel):
    """Persisted user identity for onboarding re-runs."""

    name: str = ""
    role: str = ""
    address_as: str = ""
    agent_name: str = ""
    personality: str = ""
    use_case: str = ""
    extra_instructions: str = ""


class Config(BaseModel):
    """Root configuration model for pyclaw."""

    user: UserConfig = Field(default_factory=UserConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    bindings: list[AgentBinding] = Field(default_factory=list)
    session: SessionConfig = Field(default_factory=SessionConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    model_list: list[ModelConfig] = Field(default_factory=list)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    devices: DevicesConfig = Field(default_factory=DevicesConfig)

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".pyclaw"

    @property
    def default_workspace(self) -> Path:
        ws = self.agents.defaults.workspace
        return Path(ws).expanduser()
