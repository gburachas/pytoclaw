"""Agent loop — core message processing engine."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pytoclaw.agent.instance import AgentInstance
from pytoclaw.agent.registry import AgentRegistry
from pytoclaw.bus.message_bus import MessageBus
from pytoclaw.config.models import Config
from pytoclaw.models import (
    InboundMessage,
    LLMResponse,
    Message,
    OutboundMessage,
    RouteInput,
    ToolCall,
)
from pytoclaw.protocols import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ProcessOptions:
    session_key: str = ""
    channel: str = ""
    chat_id: str = ""
    user_message: str = ""
    default_response: str = ""
    enable_summary: bool = True
    send_response: bool = True
    no_history: bool = False


class AgentLoop:
    """Core agent processing loop."""

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        provider: LLMProvider,
    ):
        self._config = config
        self._bus = bus
        self._provider = provider
        self._registry = AgentRegistry(config, provider)
        self._running = False
        self._summarize_threshold = 20  # messages before summarization

    async def run(self) -> None:
        """Run the main message processing loop."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            msg = await self._bus.consume_inbound()
            if msg is None:
                continue
            try:
                await self._handle_message(msg)
            except Exception:
                logger.exception("Error processing message")

    def stop(self) -> None:
        self._running = False

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli",
    ) -> str:
        """Process a message directly (for CLI mode)."""
        agent = self._registry.get_default_agent()
        opts = ProcessOptions(
            session_key=session_key,
            user_message=content,
            send_response=False,
            enable_summary=True,
        )
        return await self._run_agent_loop(agent, opts)

    async def _handle_message(self, msg: InboundMessage) -> None:
        """Route and process an inbound message."""
        route_input = RouteInput(
            channel=msg.channel,
            account_id=msg.sender_id,
        )
        route = self._registry.resolve_route(route_input)
        agent = self._registry.get_agent(route.agent_id) or self._registry.get_default_agent()

        opts = ProcessOptions(
            session_key=route.session_key or msg.session_key or "default",
            channel=msg.channel,
            chat_id=msg.chat_id,
            user_message=msg.content,
            send_response=True,
            enable_summary=True,
        )

        response = await self._run_agent_loop(agent, opts)

        if opts.send_response and response:
            await self._bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response,
            ))

    async def _run_agent_loop(
        self,
        agent: AgentInstance,
        opts: ProcessOptions,
    ) -> str:
        """Run the LLM iteration loop for one message."""
        # Load or create session
        history = [] if opts.no_history else agent.sessions.get_history(opts.session_key)
        summary = agent.sessions.get_summary(opts.session_key)

        # Save user message to session
        if not opts.no_history:
            agent.sessions.add_message(opts.session_key, "user", opts.user_message)

        # Build context
        messages = agent.context_builder.build_messages(
            history=history,
            summary=summary,
            current_message=opts.user_message,
            channel=opts.channel,
            chat_id=opts.chat_id,
        )

        # LLM iteration loop
        response_text = ""
        for iteration in range(agent.max_iterations):
            try:
                response = await self._call_llm(agent, messages)
            except Exception as e:
                error_msg = str(e)
                # Extract useful message from provider errors
                if "404" in error_msg or "model" in error_msg.lower():
                    response_text = (
                        f"Model error: {error_msg}\n\n"
                        f"Current model: {agent.model}. "
                        f"Use /model to check, or re-run `pytoclaw onboard` to reconfigure."
                    )
                else:
                    response_text = f"LLM provider error: {error_msg}"
                logger.error("LLM call failed: %s", error_msg)
                break

            # If no tool calls, we have our final response
            if not response.tool_calls:
                response_text = response.content
                break

            # Process tool calls
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)
            if not opts.no_history:
                agent.sessions.add_full_message(opts.session_key, assistant_msg)

            for tc in response.tool_calls:
                tool_name = tc.function.name if tc.function else tc.name
                tool_args = (
                    json.loads(tc.function.arguments)
                    if tc.function and tc.function.arguments
                    else tc.arguments
                )

                logger.info("Tool call: %s(%s)", tool_name, list(tool_args.keys()))
                result = await agent.tools.execute(
                    tool_name, tool_args, opts.channel, opts.chat_id
                )

                tool_msg = Message(
                    role="tool",
                    content=result.for_llm,
                    tool_call_id=tc.id,
                )
                messages.append(tool_msg)
                if not opts.no_history:
                    agent.sessions.add_full_message(opts.session_key, tool_msg)

        else:
            response_text = response.content or opts.default_response or "(max iterations reached)"

        # Save assistant response
        if response_text and not opts.no_history:
            agent.sessions.add_message(opts.session_key, "assistant", response_text)
            agent.sessions.save(opts.session_key)

        # Maybe summarize
        if opts.enable_summary:
            await self._maybe_summarize(agent, opts.session_key)

        return response_text

    async def _call_llm(self, agent: AgentInstance, messages: list[Message]) -> LLMResponse:
        """Call the LLM provider."""
        tool_defs = agent.tools.get_definitions()
        options: dict[str, Any] = {
            "max_tokens": agent.max_tokens,
            "temperature": agent.temperature,
        }
        return await agent.provider.chat(messages, tool_defs, agent.model, options)

    async def _maybe_summarize(self, agent: AgentInstance, session_key: str) -> None:
        """Summarize conversation if it exceeds threshold."""
        history = agent.sessions.get_history(session_key)
        if len(history) < self._summarize_threshold:
            return

        # Keep last few messages, summarize the rest
        to_summarize = history[:-4]
        if not to_summarize:
            return

        summary_prompt = (
            "Summarize the following conversation concisely, "
            "capturing key facts, decisions, and context:\n\n"
        )
        for msg in to_summarize:
            summary_prompt += f"[{msg.role}]: {msg.content[:500]}\n"

        try:
            summary_response = await agent.provider.chat(
                [Message(role="user", content=summary_prompt)],
                [],
                agent.model,
                {"max_tokens": 1000, "temperature": 0.3},
            )
            existing_summary = agent.sessions.get_summary(session_key)
            new_summary = summary_response.content
            if existing_summary:
                new_summary = f"{existing_summary}\n\n{new_summary}"
            agent.sessions.set_summary(session_key, new_summary)
            agent.sessions.set_history(session_key, history[-4:])
            agent.sessions.save(session_key)
            logger.info("Session %s summarized", session_key)
        except Exception:
            logger.exception("Failed to summarize session %s", session_key)
