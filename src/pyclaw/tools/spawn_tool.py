"""Spawn tool — create subagent for background work."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from pyclaw.models import ToolResult
from pyclaw.protocols import AsyncCallback, AsyncTool, ContextualTool

logger = logging.getLogger(__name__)

# Type for the function that actually processes a background task.
# Signature: async def handler(task: str, session_key: str) -> str
BackgroundHandler = Callable[[str, str], Any]


class SpawnTool(ContextualTool, AsyncTool):
    """Spawn a subagent to handle a task in the background.

    Requires a background_handler to be set — this is the function that
    actually processes the task asynchronously (typically AgentLoop.process_direct).
    Without a handler, the tool returns an error.
    """

    def __init__(self) -> None:
        self._channel = ""
        self._chat_id = ""
        self._callback: AsyncCallback | None = None
        self._allowlist_checker: Callable[[str], bool] | None = None
        self._background_handler: BackgroundHandler | None = None
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

    def name(self) -> str:
        return "spawn"

    def description(self) -> str:
        return (
            "Spawn a background subagent to handle a complex or long-running task. "
            "The subagent runs independently and reports results when done."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the subagent to perform",
                },
                "label": {
                    "type": "string",
                    "description": "Short label for the spawned task",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional: target agent ID to handle the task",
                },
            },
            "required": ["task"],
        }

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    def set_callback(self, callback: AsyncCallback) -> None:
        self._callback = callback

    def set_allowlist_checker(self, checker: Callable[[str], bool]) -> None:
        self._allowlist_checker = checker

    def set_background_handler(self, handler: BackgroundHandler) -> None:
        """Set the async function that processes background tasks."""
        self._background_handler = handler

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        task = args.get("task", "").strip()
        if not task:
            return ToolResult.error("No task provided")

        label = args.get("label", task[:50])
        agent_id = args.get("agent_id", "")

        # Check allowlist if agent_id specified
        if agent_id and self._allowlist_checker:
            if not self._allowlist_checker(agent_id):
                return ToolResult.error(
                    f"Agent '{agent_id}' is not in the allowed subagent list"
                )

        if self._background_handler is None:
            return ToolResult.error(
                "Background task execution is not configured. "
                "The spawn tool requires a running agent loop."
            )

        logger.info("Spawning background task: %s", label)

        # Create a unique session key for the background task
        import time
        session_key = f"spawn_{int(time.time() * 1000)}"

        # Capture callback and channel info for result delivery
        callback = self._callback
        channel = self._channel
        chat_id = self._chat_id
        handler = self._background_handler

        async def _run_background() -> None:
            try:
                result = await handler(task, session_key)
                logger.info("Background task '%s' completed", label)
                if callback:
                    await callback(ToolResult.success(
                        f"Background task '{label}' completed:\n{result}"
                    ))
            except Exception as e:
                logger.exception("Background task '%s' failed", label)
                if callback:
                    await callback(ToolResult.error(
                        f"Background task '{label}' failed: {e}"
                    ))
            finally:
                self._active_tasks.pop(session_key, None)

        bg_task = asyncio.create_task(_run_background())
        self._active_tasks[session_key] = bg_task

        return ToolResult.async_result(
            f"Background task '{label}' spawned (session: {session_key}). "
            "Results will be delivered when complete."
        )
