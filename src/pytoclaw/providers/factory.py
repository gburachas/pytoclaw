"""Provider factory — creates the correct LLM provider from config."""

from __future__ import annotations

import logging
from typing import Any

from pytoclaw.config.models import Config, ModelConfig, ProvidersConfig
from pytoclaw.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Provider prefix → protocol mapping
ANTHROPIC_PREFIXES = ("anthropic/", "claude")
COPILOT_PREFIXES = ("copilot/",)


def create_provider(
    model_name: str,
    config: Config,
) -> LLMProvider:
    """Create an LLM provider based on model name and config.

    Resolution order:
    1. Check model_list for an explicit entry matching model_name
    2. Infer protocol from model name prefix (anthropic/, openai/, etc.)
    3. Fall back to OpenAI-compatible protocol
    """
    # Check model_list first
    model_cfg = _find_model_config(model_name, config.model_list)

    if model_cfg:
        model_id = model_cfg.model or model_name
        api_key = model_cfg.api_key
        api_base = model_cfg.api_base
    else:
        model_id = model_name
        api_key = ""
        api_base = ""

    # Determine protocol from model identifier
    if any(model_id.startswith(p) for p in ANTHROPIC_PREFIXES):
        return _create_anthropic(model_id, api_key, api_base, config.providers)
    elif any(model_id.startswith(p) for p in COPILOT_PREFIXES):
        raise NotImplementedError("GitHub Copilot provider not yet implemented")
    else:
        # Check if we have OAuth credentials for OpenAI Codex
        codex = _try_create_codex(model_id, config)
        if codex:
            return codex
        return _create_openai(model_id, api_key, api_base, config.providers)


def _find_model_config(name: str, model_list: list[ModelConfig]) -> ModelConfig | None:
    for mc in model_list:
        if mc.model_name == name:
            return mc
    return None


def _create_openai(
    model_id: str,
    api_key: str,
    api_base: str,
    providers: ProvidersConfig,
) -> LLMProvider:
    from pytoclaw.providers.openai_provider import OpenAIProvider

    # Strip provider prefix if present (e.g., "openai/gpt-4o" → "gpt-4o")
    actual_model = model_id
    for prefix in ("openai/", "openrouter/", "groq/", "ollama/", "deepseek/", "gemini/", "qwen/"):
        if model_id.startswith(prefix):
            actual_model = model_id[len(prefix):]
            break

    # Resolve API key from provider config if not set
    if not api_key:
        if model_id.startswith("openrouter/"):
            api_key = providers.openrouter.api_key
            api_base = api_base or providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        elif model_id.startswith("groq/"):
            api_key = providers.groq.api_key
            api_base = api_base or providers.groq.api_base or "https://api.groq.com/openai/v1"
        elif model_id.startswith("ollama/"):
            api_base = api_base or providers.ollama.api_base or "http://localhost:11434/v1"
            api_key = api_key or "ollama"
        elif model_id.startswith("deepseek/"):
            api_key = providers.deepseek.api_key
            api_base = api_base or providers.deepseek.api_base or "https://api.deepseek.com/v1"
        else:
            api_key = providers.openai.api_key
            api_base = api_base or providers.openai.api_base or ""

    return OpenAIProvider(model=actual_model, api_key=api_key, api_base=api_base)


def _create_anthropic(
    model_id: str,
    api_key: str,
    api_base: str,
    providers: ProvidersConfig,
) -> LLMProvider:
    from pytoclaw.providers.anthropic_provider import AnthropicProvider

    actual_model = model_id
    if model_id.startswith("anthropic/"):
        actual_model = model_id[len("anthropic/"):]

    if not api_key:
        api_key = providers.anthropic.api_key
        api_base = api_base or providers.anthropic.api_base or ""

    return AnthropicProvider(model=actual_model, api_key=api_key, api_base=api_base)


def _try_create_codex(model_id: str, config: Config) -> LLMProvider | None:
    """Try to create a Codex provider using stored OAuth credentials."""
    try:
        from pytoclaw.auth.credentials import CredentialStore
        store = CredentialStore(config.config_dir)
        cred = store.get("openai-codex")
        if cred is None or cred.auth_type != "oauth":
            return None

        from pytoclaw.providers.codex_provider import CodexProvider
        return CodexProvider(
            access_token=cred.access_token,
            account_id=cred.account_id,
            default_model=model_id,
        )
    except Exception:
        return None
