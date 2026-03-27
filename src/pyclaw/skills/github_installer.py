"""GitHub installer — install skills from GitHub repositories."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_GITHUB_RAW = "https://raw.githubusercontent.com"
_SKILLS_LIST_URL = f"{_GITHUB_RAW}/sipeed/picoclaw-skills/main/skills.json"
_TIMEOUT = 15.0


class AvailableSkill:
    """A skill available from the community skills repo."""

    def __init__(
        self,
        name: str = "",
        repository: str = "",
        description: str = "",
        author: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.repository = repository
        self.description = description
        self.author = author
        self.tags = tags or []


class GitHubInstaller:
    """Install skills from GitHub repos (fetches SKILL.md from main branch)."""

    def __init__(self, workspace: str) -> None:
        self._workspace = workspace

    async def install_from_github(self, repo: str, force: bool = False) -> str:
        """Install a skill from a GitHub repo.

        repo should be in the form "owner/repo-name".
        Returns the installed skill directory path.
        """
        skill_name = repo.rsplit("/", 1)[-1] if "/" in repo else repo
        skill_dir = Path(self._workspace) / "skills" / skill_name

        if skill_dir.exists() and not force:
            raise FileExistsError(f"Skill '{skill_name}' already exists")

        url = f"{_GITHUB_RAW}/{repo}/main/SKILL.md"

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch skill: HTTP {resp.status_code}")
            content = resp.text

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        return str(skill_dir)

    async def list_available(self) -> list[AvailableSkill]:
        """Fetch the community skills list from GitHub."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_SKILLS_LIST_URL)
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch skills list: HTTP {resp.status_code}")

            data = resp.json()

        skills: list[AvailableSkill] = []
        for item in data:
            skills.append(AvailableSkill(
                name=item.get("name", ""),
                repository=item.get("repository", ""),
                description=item.get("description", ""),
                author=item.get("author", ""),
                tags=item.get("tags", []),
            ))
        return skills
