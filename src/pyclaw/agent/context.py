"""Context builder — assembles system prompt from workspace files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pyclaw.memory.store import MemoryStore
from pyclaw.models import Message
from pyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from pyclaw.skills.loader import SkillsLoader

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds the system prompt and message context for LLM calls."""

    def __init__(self, workspace: str):
        self._workspace = Path(workspace).expanduser().resolve()
        self._memory = MemoryStore(workspace)
        self._tools: ToolRegistry | None = None
        self._skills_loader: SkillsLoader | None = None
        self._skills_filter: list[str] | None = None

    def set_tools_registry(self, registry: ToolRegistry) -> None:
        self._tools = registry

    def set_skills_loader(
        self,
        loader: SkillsLoader,
        filter_names: list[str] | None = None,
    ) -> None:
        """Configure the skills loader for progressive disclosure."""
        self._skills_loader = loader
        self._skills_filter = filter_names

    def build_system_prompt(self) -> str:
        """Assemble system prompt from workspace files + tools + memory."""
        parts = []

        # Load bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Load skills
        skills_info = self._load_skills()
        if skills_info:
            parts.append(f"# Active Skills\n{skills_info}")

        # Load tool descriptions
        if self._tools:
            tool_names = self._tools.list_names()
            if tool_names:
                parts.append(f"# Available Tools\n{', '.join(tool_names)}")

        # Load memory
        memory_ctx = self._memory.get_memory_context()
        if memory_ctx:
            parts.append(f"# Memory\n{memory_ctx}")

        return "\n\n".join(parts)

    def build_messages(
        self,
        history: list[Message],
        summary: str,
        current_message: str,
        media: list[str] | None = None,
        channel: str = "",
        chat_id: str = "",
    ) -> list[Message]:
        """Build the full message list for an LLM call."""
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt()
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))

        # Summary of older conversation
        if summary:
            messages.append(Message(
                role="system",
                content=f"Summary of earlier conversation:\n{summary}",
            ))

        # Conversation history
        messages.extend(history)

        # Current user message
        if current_message:
            messages.append(Message(role="user", content=current_message))

        return messages

    def _load_bootstrap_files(self) -> str:
        """Load IDENTITY.md, SOUL.md, AGENT.md, USER.md from workspace."""
        parts = []
        for filename in ["IDENTITY.md", "SOUL.md", "AGENT.md", "USER.md"]:
            path = self._workspace / filename
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
        return "\n\n".join(parts)

    def _load_skills(self) -> str:
        """Load skills using progressive disclosure via SkillsLoader.

        If a SkillsLoader is configured, uses XML summary format.
        Falls back to reading workspace/skills/ directly for backward compatibility.
        """
        if self._skills_loader is not None:
            summary = self._skills_loader.build_skills_summary(self._skills_filter)
            if summary:
                return (
                    "To use a skill, read its full SKILL.md using the "
                    "read_file tool at the location shown.\n\n" + summary
                )
            return ""

        # Fallback: read skills directly from workspace.
        skills_dir = self._workspace / "skills"
        if not skills_dir.exists():
            return ""
        parts = []
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"## {skill_dir.name}\n{content}")
        return "\n\n".join(parts)
