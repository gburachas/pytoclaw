"""Base provider class with shared utilities."""

from __future__ import annotations

import logging
from typing import Any, Callable

from pyclaw.models import LLMResponse, Message, ToolDefinition
from pyclaw.protocols import LLMProvider

logger = logging.getLogger(__name__)


class BaseProvider(LLMProvider):
    """Base class for LLM providers with common functionality."""

    def __init__(self, model: str, api_key: str, api_base: str = "", **kwargs: Any):
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._extra = kwargs

    def get_default_model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
        on_chunk: Callable[[str], Any] | None = None,
    ) -> LLMResponse:
        """Streaming chat with incremental output. Default: falls back to non-streaming."""
        return await self.chat(messages, tools, model, options)
