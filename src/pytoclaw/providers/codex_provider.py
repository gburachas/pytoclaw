"""OpenAI Codex Responses API provider.

Uses the ChatGPT backend API (https://chatgpt.com/backend-api/codex/responses)
with OAuth bearer tokens from ChatGPT Pro/Plus subscriptions.

The Codex API requires streaming (stream=true). We consume the SSE stream
and accumulate the full response.
"""

from __future__ import annotations

import json
import logging
import platform
import time
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
MAX_RETRIES = 3
BASE_DELAY_S = 1.0


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
            "stream": True,
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
        headers["Accept"] = "text/event-stream"

        # Retry loop for transient errors
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._stream_request(url, body, headers)
            except _RetryableError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY_S * (2 ** attempt)
                    logger.warning("Codex request failed (attempt %d), retrying in %.1fs: %s", attempt + 1, delay, e)
                    import asyncio
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(str(e)) from e
            except RuntimeError:
                raise

        raise RuntimeError(str(last_error) if last_error else "Codex request failed")

    async def _stream_request(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> LLMResponse:
        """Send a streaming request and accumulate the SSE response."""
        content_parts: list[str] = []
        tool_calls_by_idx: dict[str, dict[str, str]] = {}
        usage_data: dict[str, int] = {}
        stop_reason = "stop"

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    error_str = error_text.decode(errors="replace")
                    if _is_retryable(resp.status_code, error_str):
                        raise _RetryableError(f"Codex API error {resp.status_code}: {error_str[:300]}")
                    _raise_friendly_error(resp.status_code, error_str)

                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk

                    while "\n\n" in buffer:
                        event_text, buffer = buffer.split("\n\n", 1)
                        data_lines = [
                            line[5:].strip()
                            for line in event_text.split("\n")
                            if line.startswith("data:")
                        ]
                        if not data_lines:
                            continue
                        data_str = "\n".join(data_lines).strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        # Handle errors from the stream
                        if event_type == "error":
                            msg = event.get("message", event.get("code", "Unknown error"))
                            raise RuntimeError(f"Codex stream error: {msg}")

                        if event_type == "response.failed":
                            err = event.get("response", {}).get("error", {})
                            msg = err.get("message", "Response failed")
                            raise RuntimeError(msg)

                        # Text content deltas
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta", "")
                            if delta:
                                content_parts.append(delta)

                        # Function call arguments delta
                        elif event_type == "response.function_call_arguments.delta":
                            item_id = event.get("item_id", "")
                            delta = event.get("delta", "")
                            if item_id not in tool_calls_by_idx:
                                tool_calls_by_idx[item_id] = {"id": item_id, "name": "", "arguments": ""}
                            tool_calls_by_idx[item_id]["arguments"] += delta

                        # Output item added (captures function call name)
                        elif event_type == "response.output_item.added":
                            item = event.get("item", {})
                            if item.get("type") == "function_call":
                                item_id = item.get("id", item.get("call_id", ""))
                                tool_calls_by_idx[item_id] = {
                                    "id": item.get("call_id", item_id),
                                    "name": item.get("name", ""),
                                    "arguments": "",
                                }

                        # Response completed — extract usage
                        elif event_type in ("response.completed", "response.done"):
                            response_obj = event.get("response", {})
                            usage = response_obj.get("usage", {})
                            if usage:
                                usage_data["input"] = usage.get("input_tokens", 0)
                                usage_data["output"] = usage.get("output_tokens", 0)
                            status = response_obj.get("status", "completed")
                            if status != "completed":
                                stop_reason = status

        # Build final response
        content = "".join(content_parts)
        tool_call_list = []
        for tc_data in tool_calls_by_idx.values():
            tool_call_list.append(ToolCall(
                id=tc_data["id"],
                function=FunctionCall(
                    name=tc_data["name"],
                    arguments=tc_data["arguments"] or "{}",
                ),
            ))

        usage = UsageInfo(
            prompt_tokens=usage_data.get("input", 0),
            completion_tokens=usage_data.get("output", 0),
        ) if usage_data else None

        finish_reason = "tool_calls" if tool_call_list else stop_reason

        return LLMResponse(
            content=content,
            tool_calls=tool_call_list if tool_call_list else None,
            usage=usage,
            finish_reason=finish_reason,
        )

    def _build_headers(self) -> dict[str, str]:
        ua = f"pytoclaw ({platform.system()} {platform.release()}; {platform.machine()})"
        return {
            "Authorization": f"Bearer {self._access_token}",
            "chatgpt-account-id": self._account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "pytoclaw",
            "User-Agent": ua,
            "Content-Type": "application/json",
        }


class _RetryableError(Exception):
    """Raised for transient errors that should be retried."""
    pass


def _is_retryable(status: int, error_text: str) -> bool:
    if status in (429, 500, 502, 503, 504):
        return True
    import re
    return bool(re.search(r"rate.?limit|overloaded|service.?unavailable|upstream.?connect", error_text, re.IGNORECASE))


def _raise_friendly_error(status: int, error_text: str) -> None:
    """Parse error response and raise a friendly RuntimeError."""
    try:
        data = json.loads(error_text)
        err = data.get("error", {})
        code = err.get("code", "")
        if "usage_limit" in code or status == 429:
            plan = err.get("plan_type", "")
            resets = err.get("resets_at")
            msg = "ChatGPT usage limit reached"
            if plan:
                msg += f" ({plan} plan)"
            if resets:
                mins = max(0, round((resets * 1000 - time.time() * 1000) / 60000))
                msg += f". Try again in ~{mins} min"
            raise RuntimeError(msg)
        if err.get("message"):
            raise RuntimeError(f"Codex API error: {err['message']}")
    except (json.JSONDecodeError, RuntimeError):
        raise
    raise RuntimeError(f"Codex API error {status}: {error_text[:500]}")


def _extract_system_prompt(messages: list[Message]) -> str:
    for msg in messages:
        if msg.role == "system":
            return msg.content
    return ""


def _convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal messages to Responses API input format."""
    result = []
    for msg in messages:
        if msg.role == "system":
            continue

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
