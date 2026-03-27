"""OpenAI-compatible provider (covers OpenAI, OpenRouter, Groq, Ollama, etc.)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from openai import AsyncOpenAI

from pyclaw.models import (
    FunctionCall,
    LLMResponse,
    Message,
    ToolCall,
    ToolDefinition,
    UsageInfo,
)
from pyclaw.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs."""

    def __init__(self, model: str, api_key: str, api_base: str = "", **kwargs: Any):
        super().__init__(model, api_key, api_base, **kwargs)
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if api_base:
            client_kwargs["base_url"] = api_base
        self._client = AsyncOpenAI(**client_kwargs)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        opts = options or {}
        model = model or self._model

        # Convert messages to OpenAI format
        oai_messages = _to_openai_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
        }

        if tools:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]

        if "max_tokens" in opts:
            kwargs["max_tokens"] = opts["max_tokens"]
        if "temperature" in opts:
            kwargs["temperature"] = opts["temperature"]

        response = await self._client.chat.completions.create(**kwargs)
        return _from_openai_response(response)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
        on_chunk: "Callable[[str], Any] | None" = None,
    ) -> LLMResponse:
        """Streaming chat — calls on_chunk(text) for each content delta."""
        from pyclaw.providers.streaming import stream_openai_response

        opts = options or {}
        model = model or self._model
        oai_messages = _to_openai_messages(messages)

        oai_tools = [_to_openai_tool(t) for t in tools] if tools else None

        kwargs: dict[str, Any] = {}
        if "max_tokens" in opts:
            kwargs["max_tokens"] = opts["max_tokens"]
        if "temperature" in opts:
            kwargs["temperature"] = opts["temperature"]

        # The streaming function creates its own kwargs internally,
        # but we need to pass extra options. Patch them onto the client call.
        client_kwargs: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "stream": True,
        }
        if oai_tools:
            client_kwargs["tools"] = oai_tools
        client_kwargs.update(kwargs)

        return await _stream_openai_raw(self._client, client_kwargs, on_chunk)


def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert pyclaw Messages to OpenAI API format."""
    result = []
    for msg in messages:
        oai_msg: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            oai_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name if tc.function else tc.name,
                        "arguments": (
                            tc.function.arguments
                            if tc.function
                            else json.dumps(tc.arguments)
                        ),
                    },
                }
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            oai_msg["tool_call_id"] = msg.tool_call_id
        result.append(oai_msg)
    return result


def _to_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Convert ToolDefinition to OpenAI tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.function.name,
            "description": tool.function.description,
            "parameters": tool.function.parameters,
        },
    }


def _from_openai_response(response: Any) -> LLMResponse:
    """Convert OpenAI response to LLMResponse."""
    choice = response.choices[0]
    message = choice.message

    tool_calls = []
    if message.tool_calls:
        for tc in message.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    type="function",
                    function=FunctionCall(
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    ),
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                )
            )

    usage = None
    if response.usage:
        usage = UsageInfo(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )

    return LLMResponse(
        content=message.content or "",
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "",
        usage=usage,
    )


async def _stream_openai_raw(
    client: Any,
    kwargs: dict[str, Any],
    on_chunk: Callable[[str], Any] | None = None,
) -> LLMResponse:
    """Low-level OpenAI streaming that accumulates content and tool calls."""
    content_parts: list[str] = []
    tool_calls_by_idx: dict[int, dict[str, str]] = {}

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue

        if delta.content:
            content_parts.append(delta.content)
            if on_chunk:
                try:
                    result = on_chunk(delta.content)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_by_idx:
                    tool_calls_by_idx[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tool_calls_by_idx[idx]["id"] = tc.id
                if tc.function and tc.function.name:
                    tool_calls_by_idx[idx]["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    tool_calls_by_idx[idx]["arguments"] += tc.function.arguments

    content = "".join(content_parts)
    tool_calls = []
    for idx in sorted(tool_calls_by_idx):
        tc_data = tool_calls_by_idx[idx]
        tool_calls.append(ToolCall(
            id=tc_data["id"],
            function=FunctionCall(name=tc_data["name"], arguments=tc_data["arguments"]),
            name=tc_data["name"],
            arguments=json.loads(tc_data["arguments"]) if tc_data["arguments"] else {},
        ))

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
    )
