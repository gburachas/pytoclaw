"""Tests for the skill creator tool."""

import asyncio
from pathlib import Path

import pytest

from pyclaw.skills.creator import CreateSkillTool, build_synergy_context
from pyclaw.skills.loader import SkillsLoader


def _make_skill(base: Path, name: str, description: str) -> None:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content)


class TestBuildSynergyContext:
    def test_empty_skills(self, tmp_path):
        loader = SkillsLoader(workspace_skills=tmp_path / "empty")
        ctx = build_synergy_context(loader)
        assert "No skills are currently installed" in ctx
        assert "Guidelines" in ctx

    def test_with_existing_skills(self, tmp_path):
        ws = tmp_path / "skills"
        ws.mkdir()
        _make_skill(ws, "weather", "Get weather info")
        _make_skill(ws, "calculator", "Do math")

        loader = SkillsLoader(workspace_skills=ws)
        ctx = build_synergy_context(loader)
        assert "weather" in ctx
        assert "calculator" in ctx
        assert "Delegate to existing skills" in ctx
        assert "Identify gaps" in ctx


class TestCreateSkillTool:
    def test_name(self, tmp_path):
        loader = SkillsLoader(workspace_skills=tmp_path)
        tool = CreateSkillTool(str(tmp_path), loader)
        assert tool.name() == "create_skill"

    def test_create_success(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        skills_dir = ws / "skills"
        skills_dir.mkdir()

        loader = SkillsLoader(workspace_skills=skills_dir)
        tool = CreateSkillTool(str(ws), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "new-skill",
                "description": "A brand new skill",
                "body": "# Instructions\nDo the thing.",
            })
        )
        assert not result.is_error
        assert "new-skill" in result.for_llm

        # Verify file was created
        skill_file = ws / "skills" / "new-skill" / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text()
        assert "name: new-skill" in content
        assert "description: A brand new skill" in content
        assert "# Instructions" in content

    def test_create_collision(self, tmp_path):
        ws = tmp_path / "workspace"
        skills_dir = ws / "skills"
        _make_skill(skills_dir, "existing", "Already exists")

        loader = SkillsLoader(workspace_skills=skills_dir)
        tool = CreateSkillTool(str(ws), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "existing",
                "description": "Try to overwrite",
                "body": "# New body",
            })
        )
        assert result.is_error
        assert "already exists" in result.for_llm

    def test_invalid_name(self, tmp_path):
        loader = SkillsLoader()
        tool = CreateSkillTool(str(tmp_path), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "bad name!",
                "description": "desc",
                "body": "body",
            })
        )
        assert result.is_error
        assert "alphanumeric" in result.for_llm

    def test_empty_name(self, tmp_path):
        loader = SkillsLoader()
        tool = CreateSkillTool(str(tmp_path), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "",
                "description": "desc",
                "body": "body",
            })
        )
        assert result.is_error

    def test_empty_description(self, tmp_path):
        loader = SkillsLoader()
        tool = CreateSkillTool(str(tmp_path), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "test-skill",
                "description": "",
                "body": "body",
            })
        )
        assert result.is_error

    def test_synergy_context_in_output(self, tmp_path):
        ws = tmp_path / "workspace"
        skills_dir = ws / "skills"
        _make_skill(skills_dir, "existing-skill", "An existing skill")

        loader = SkillsLoader(workspace_skills=skills_dir)
        tool = CreateSkillTool(str(ws), loader)

        result = asyncio.get_event_loop().run_until_complete(
            tool.execute({
                "skill_name": "new-skill",
                "description": "A new skill",
                "body": "# Body",
            })
        )
        assert not result.is_error
        # Synergy context should mention existing skills
        assert "existing-skill" in result.for_llm
        assert "Guidelines" in result.for_llm
