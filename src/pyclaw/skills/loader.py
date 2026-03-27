"""4-tier skill loader — workspace > project > global > builtin."""

from __future__ import annotations

import logging
from pathlib import Path

from pyclaw.skills.frontmatter import parse_metadata, strip_frontmatter
from pyclaw.skills.models import SkillInfo, SkillSource

logger = logging.getLogger(__name__)


def _escape_xml(s: str) -> str:
    """Escape XML special characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SkillsLoader:
    """Discovers and loads skills from a 4-tier directory hierarchy.

    Priority (highest shadows lowest): workspace → project → global → builtin.
    """

    def __init__(
        self,
        workspace_skills: Path | None = None,
        project_skills: Path | None = None,
        global_skills: Path | None = None,
        builtin_skills: Path | None = None,
    ) -> None:
        self._tiers: list[tuple[Path, SkillSource]] = []
        if workspace_skills is not None:
            self._tiers.append((Path(workspace_skills), SkillSource.WORKSPACE))
        if project_skills is not None:
            self._tiers.append((Path(project_skills), SkillSource.PROJECT))
        if global_skills is not None:
            self._tiers.append((Path(global_skills), SkillSource.GLOBAL))
        if builtin_skills is not None:
            self._tiers.append((Path(builtin_skills), SkillSource.BUILTIN))

    def list_skills(self) -> list[SkillInfo]:
        """Walk all tiers and return deduplicated skill list.

        Higher-priority tiers shadow lower ones by name.
        """
        seen_names: set[str] = set()
        skills: list[SkillInfo] = []

        for tier_path, source in self._tiers:
            if not tier_path.exists():
                continue
            try:
                dirs = sorted(tier_path.iterdir())
            except OSError:
                continue

            for skill_dir in dirs:
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    continue

                try:
                    content = skill_file.read_text(encoding="utf-8")
                except OSError:
                    continue

                metadata = parse_metadata(content, fallback_name=skill_dir.name)
                name = metadata.name or skill_dir.name

                if name in seen_names:
                    continue

                try:
                    info = SkillInfo(
                        name=name,
                        path=str(skill_file),
                        source=source,
                        description=metadata.description,
                    )
                except ValueError as e:
                    logger.warning(
                        "Invalid skill from %s: name=%s error=%s",
                        source.value,
                        name,
                        e,
                    )
                    continue

                seen_names.add(name)
                skills.append(info)

        return skills

    def load_skill(self, name: str) -> tuple[str, bool]:
        """Load a skill's body (frontmatter stripped) by name.

        Searches tiers in priority order and returns (body, found).
        """
        for tier_path, _source in self._tiers:
            skill_file = tier_path / name / "SKILL.md"
            if skill_file.exists():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    return strip_frontmatter(content), True
                except OSError:
                    continue
        return "", False

    def build_skills_summary(
        self,
        filter_names: list[str] | None = None,
    ) -> str:
        """Build XML summary of skills for progressive disclosure.

        If filter_names is provided, only include skills whose names are in the list.
        """
        all_skills = self.list_skills()
        if not all_skills:
            return ""

        if filter_names:
            filter_set = set(filter_names)
            all_skills = [s for s in all_skills if s.name in filter_set]

        if not all_skills:
            return ""

        lines: list[str] = ["<skills>"]
        for s in all_skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{_escape_xml(s.name)}</name>")
            lines.append(f"    <description>{_escape_xml(s.description)}</description>")
            lines.append(f"    <location>{_escape_xml(s.path)}</location>")
            lines.append(f"    <source>{s.source.value}</source>")
            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)
