"""Skill creator tool — LLM-driven skill creation with complement suggestions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pyclaw.models import ToolResult
from pyclaw.protocols import Tool
from pyclaw.skills.loader import SkillsLoader
from pyclaw.skills.models import NAME_PATTERN, MAX_NAME_LENGTH

logger = logging.getLogger(__name__)


def build_synergy_context(loader: SkillsLoader) -> str:
    """Summarize all existing skills and provide complement-creation guidelines.

    Returned as a formatted string the LLM can use to make informed decisions
    about new skill creation.
    """
    skills = loader.list_skills()

    lines: list[str] = ["## Existing Skills"]
    if not skills:
        lines.append("No skills are currently installed.")
    else:
        for s in skills:
            lines.append(f"- **{s.name}** ({s.source.value}): {s.description}")

    lines.append("")
    lines.append("## Guidelines for New Skills")
    lines.append("- Delegate to existing skills rather than reimplementing their functionality.")
    lines.append("- Identify gaps the new skill can fill that complement the existing set.")
    lines.append(
        "- Differentiate trigger descriptions to avoid ambiguous activation "
        "between skills."
    )

    return "\n".join(lines)


class CreateSkillTool(Tool):
    """Tool for creating new skills in the workspace."""

    def __init__(self, workspace: str, loader: SkillsLoader) -> None:
        self._workspace = workspace
        self._loader = loader

    def name(self) -> str:
        return "create_skill"

    def description(self) -> str:
        return (
            "Create a new skill in the workspace. Validates the name, checks for "
            "collisions, writes SKILL.md with frontmatter, and returns synergy "
            "context with existing skills."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name for the new skill (alphanumeric with hyphens, max 64 chars)",
                },
                "description": {
                    "type": "string",
                    "description": "Description of what the skill does and when to use it",
                },
                "body": {
                    "type": "string",
                    "description": "Markdown body with instructions for using the skill",
                },
            },
            "required": ["skill_name", "description", "body"],
        }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        skill_name = args.get("skill_name", "").strip()
        skill_desc = args.get("description", "").strip()
        body = args.get("body", "").strip()

        # Validate name.
        if not skill_name:
            return ToolResult.error("skill_name is required")
        if len(skill_name) > MAX_NAME_LENGTH:
            return ToolResult.error(f"skill_name exceeds {MAX_NAME_LENGTH} characters")
        if not NAME_PATTERN.match(skill_name):
            return ToolResult.error("skill_name must be alphanumeric with hyphens")

        if not skill_desc:
            return ToolResult.error("description is required")
        if not body:
            return ToolResult.error("body is required")

        # Check for collisions.
        skill_dir = Path(self._workspace) / "skills" / skill_name
        if skill_dir.exists():
            return ToolResult.error(
                f"Skill '{skill_name}' already exists at {skill_dir}. "
                "Remove it first or choose a different name."
            )

        # Build synergy context before creating.
        synergy = build_synergy_context(self._loader)

        # Write the skill.
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {skill_name}\ndescription: {skill_desc}\n---\n\n{body}\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        return ToolResult.success(
            f"Skill '{skill_name}' created at {skill_dir}/SKILL.md\n\n{synergy}"
        )
