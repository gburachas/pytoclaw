"""Frontmatter parsing for SKILL.md files."""

from __future__ import annotations

import json
import re

from pyclaw.skills.models import SkillMetadata

# Matches YAML frontmatter block: ---\n...\n---
# Supports \n, \r\n, and \r line endings.
_FRONTMATTER_RE = re.compile(r"(?s)^---(?:\r\n|\n|\r)(.*?)(?:\r\n|\n|\r)---")
# Same pattern but also consumes trailing newlines after the closing ---.
_STRIP_RE = re.compile(r"(?s)^---(?:\r\n|\n|\r)(.*?)(?:\r\n|\n|\r)---(?:\r\n|\n|\r)*")


def extract_frontmatter(content: str) -> str:
    """Extract raw frontmatter string from content (without the --- delimiters)."""
    match = _FRONTMATTER_RE.search(content)
    if match:
        return match.group(1)
    return ""


def strip_frontmatter(content: str) -> str:
    """Return content with frontmatter block removed."""
    return _STRIP_RE.sub("", content)


def parse_metadata(content: str, fallback_name: str = "") -> SkillMetadata:
    """Parse frontmatter into SkillMetadata.

    Tries JSON first (backward compatibility), then simple YAML key: value.
    Falls back to using fallback_name if no name is found.
    """
    fm = extract_frontmatter(content)
    if not fm:
        return SkillMetadata(name=fallback_name)

    # Try JSON first.
    try:
        data = json.loads(fm)
        return SkillMetadata(
            name=data.get("name", fallback_name),
            description=data.get("description", ""),
        )
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to simple YAML parsing.
    parsed = _parse_simple_yaml(fm)
    return SkillMetadata(
        name=parsed.get("name", fallback_name),
        description=parsed.get("description", ""),
    )


def _parse_simple_yaml(content: str) -> dict[str, str]:
    """Parse simple key: value YAML format.

    Handles all line ending styles and strips quotes from values.
    """
    result: dict[str, str] = {}

    # Normalize line endings.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    for line in normalized.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(":", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            value = parts[1].strip()
            # Remove surrounding quotes.
            value = value.strip("\"'")
            result[key] = value

    return result
