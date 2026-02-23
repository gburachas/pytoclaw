"""OpenAI Codex Responses API provider.

Uses the ChatGPT backend API (https://chatgpt.com/backend-api/codex/responses)
with OAuth bearer tokens from ChatGPT Pro/Plus subscriptions.
"""

from __future__ import annotations

import json
import logging
import platform
from typing import Any

import httpx

from pytoclaw.models import (
    LLMResponse,
    Message,
    ToolCall,
    ToolDefinition,
    FunctionCall,
    UsageInfo,
)
from pytoclaw.protocols import LLMProvider

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api"


class CodexProvider(LLMProvider):
    """OpenAI Codex provider using the Responses API with OAuth tokens."""

    def __init__(
        self,
        access_token: str,
        account_id: str,
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = "gpt-5.3-codex",
    ) -> None:
        self._access_token = access_token
        self._account_id = account_id
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    def get_default_model(self) -> str:
        return self._default_model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        model: str,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        opts = options or {}
        url = f"{self._base_url}/codex/responses"

        # Convert messages to Responses API format
        input_msgs = _convert_messages(messages)
        system_prompt = _extract_system_prompt(messages)

        body: dict[str, Any] = {
            "model": model or self._default_model,
            "store": False,
            "stream": False,
            "input": input_msgs,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }

        if system_prompt:
            body["instructions"] = system_prompt

        if tools:
            body["tools"] = _convert_tools(tools)

        if "temperature" in opts:
            body["temperature"] = opts["temperature"]

        if "max_tokens" in opts:
            body["max_output_tokens"] = opts["max_tokens"]

        headers = self._build_headers()

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=headers)

            if resp.status_code != 200:
                error_text = resp.text
                # Parse friendly error messages
                try:
                    err_data = resp.json()
                    err = err_data.get("error", {})
                    code = err.get("code", "")
                    if "usage_limit" in code or resp.status_code == 429:
                        plan = err.get("plan_type", "")
                        resets = err.get("resets_at")
                        msg = f"ChatGPT usage limit reached"
                        if plan:
                            msg += f" ({plan} plan)"
                        if resets:
                            import time
                            mins = max(0, round((resets * 1000 - time.time() * 1000) / 60000))
                            msg += f". Try again in ~{mins} min"
                        raise RuntimeError(msg)
                except (json.JSONDecodeError, RuntimeError):
                    if isinstance(resp.status_code, int) and resp.status_code == 429:
                        raise
                raise RuntimeError(
                    f"Codex API error {resp.status_code}: {error_text[:500]}"
                )

            data = resp.json()

        return _parse_response(data)

    def _build_headers(self) -> dict[str, str]:
        ua = f"pytoclaw ({platform.system()} {platform.release()}; {platform.machine()})"
        return {
            "Authorization": f"Bearer {self._access_token}",
            "chatgpt-account-id": self._account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "pytoclaw",
            "User-Agent": ua,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


def _extract_system_prompt(messages: list[Message]) -> str:
    """Extract system message content."""
    for msg in messages:
        if msg.role == "system":
            return msg.content
    return ""


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal messages to Responses API input format."""
    result = []
    for msg in messages:
        if msg.role == "system":
            continue  # System goes to instructions field

        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})

        elif msg.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}
            content = []
            if msg.content:
                content.append({"type": "output_text", "text": msg.content})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    fn = tc.function
                    if fn:
                        content.append({
                            "type": "function_call",
                            "id": tc.id,
                            "call_id": tc.id,
                            "name": fn.name,
                            "arguments": fn.arguments or "{}",
                        })
            entry["content"] = content
            result.append(entry)

        elif msg.role == "tool":
            result.append({
                "type": "function_call_output",
                "call_id": msg.tool_call_id or "",
                "output": msg.content,
            })

    return result


def _convert_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to Responses API format."""
    result = []
    for tool in tools:
        fn = tool.function
        result.append({
            "type": "function",
            "name": fn.name,
            "description": fn.description,
            "parameters": fn.parameters,
        })
    return result


def _parse_response(data: dict[str, Any]) -> LLMResponse:
    """Parse Responses API output into LLMResponse."""
    output = data.get("output", [])
    content_parts = []
    tool_calls = []

    for item in output:
        item_type = item.get("type", "")

        if item_type == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    content_parts.append(block.get("text", ""))

        elif item_type == "function_call":
            tool_calls.append(ToolCall(
                id=item.get("call_id", item.get("id", "")),
                function=FunctionCall(
                    name=item.get("name", ""),
                    arguments=item.get("arguments", "{}"),
                ),
            ))

    content = "".join(content_parts)

    # Parse usage
    usage_data = data.get("usage", {})
    usage = UsageInfo(
        prompt_tokens=usage_data.get("input_tokens", 0),
        completion_tokens=usage_data.get("output_tokens", 0),
    ) if usage_data else None

    status = data.get("status", "completed")
    finish_reason = "tool_calls" if tool_calls else ("stop" if status == "completed" else status)

    return LLMResponse(
        content=content,
        tool_calls=tool_calls if tool_calls else None,
        usage=usage,
        finish_reason=finish_reason,
    )
