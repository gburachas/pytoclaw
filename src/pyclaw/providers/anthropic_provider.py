"""Anthropic Claude provider."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from anthropic import AsyncAnthropic

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


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic Claude API."""

    def __init__(self, model: str, api_key: str, api_base: str = "", **kwargs: Any):
        super().__init__(model, api_key, api_base, **kwargs)
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if api_base:
            client_kwargs["base_url"] = api_base
        self._client = AsyncAnthropic(**client_kwargs)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        opts = options or {}
        model = model or self._model

        # Anthropic requires system message separate from messages
        system_prompt, claude_messages = _split_system(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": opts.get("max_tokens", 8192),
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]

        if "temperature" in opts:
            kwargs["temperature"] = opts["temperature"]

        response = await self._client.messages.create(**kwargs)
        return _from_anthropic_response(response)

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
        on_chunk: Callable[[str], Any] | None = None,
    ) -> LLMResponse:
        """Streaming chat — calls on_chunk(text) for each content delta."""
        opts = options or {}
        model = model or self._model

        system_prompt, claude_messages = _split_system(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": opts.get("max_tokens", 8192),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]
        if "temperature" in opts:
            kwargs["temperature"] = opts["temperature"]

        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        current_tool: dict[str, str] | None = None
        input_tokens = 0
        output_tokens = 0

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and block.type == "tool_use":
                        current_tool = {"id": block.id, "name": block.name, "input": ""}
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text"):
                        content_parts.append(delta.text)
                        if on_chunk:
                            try:
                                result = on_chunk(delta.text)
                                if asyncio.iscoroutine(result):
                                    await result
                            except Exception:
                                pass
                    elif hasattr(delta, "partial_json") and current_tool is not None:
                        current_tool["input"] += delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool is not None:
                        tool_calls.append(ToolCall(
                            id=current_tool["id"],
                            function=FunctionCall(
                                name=current_tool["name"],
                                arguments=current_tool["input"],
                            ),
                            name=current_tool["name"],
                            arguments=json.loads(current_tool["input"]) if current_tool["input"] else {},
                        ))
                        current_tool = None
                elif event.type == "message_delta":
                    if hasattr(event, "usage"):
                        output_tokens = getattr(event.usage, "output_tokens", 0)
                elif event.type == "message_start":
                    if hasattr(event, "message") and hasattr(event.message, "usage"):
                        input_tokens = getattr(event.message.usage, "input_tokens", 0)

        content = "".join(content_parts)
        usage = UsageInfo(prompt_tokens=input_tokens, completion_tokens=output_tokens)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason="tool_use" if tool_calls else "end_turn",
        )


def _split_system(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Split system message from conversation messages for Anthropic."""
    system_prompt = ""
    result = []

    for msg in messages:
        if msg.role == "system":
            system_prompt = msg.content
            continue

        if msg.role == "tool":
            result.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })
        elif msg.role == "assistant" and msg.tool_calls:
            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                name = tc.function.name if tc.function else tc.name
                args = (
                    json.loads(tc.function.arguments)
                    if tc.function
                    else tc.arguments
                )
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": name,
                    "input": args,
                })
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": msg.role, "content": msg.content})

    return system_prompt, result


def _to_anthropic_tool(tool: ToolDefinition) -> dict[str, Any]:
    """Convert ToolDefinition to Anthropic tool format."""
    return {
        "name": tool.function.name,
        "description": tool.function.description,
        "input_schema": tool.function.parameters,
    }


def _from_anthropic_response(response: Any) -> LLMResponse:
    """Convert Anthropic response to LLMResponse."""
    content = ""
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            content += block.text
        elif block.type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    type="function",
                    function=FunctionCall(
                        name=block.name,
                        arguments=json.dumps(block.input),
                    ),
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                )
            )

    usage = None
    if response.usage:
        usage = UsageInfo(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=response.stop_reason or "",
        usage=usage,
    )
