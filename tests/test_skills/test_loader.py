"""Tests for the 4-tier skill loader."""

import pytest
from pathlib import Path

from pyclaw.skills.loader import SkillsLoader
from pyclaw.skills.models import SkillSource


@pytest.fixture
def skill_dirs(tmp_path):
    """Create a temp directory structure with skills at each tier."""
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    global_ = tmp_path / "global"
    builtin = tmp_path / "builtin"

    for d in [workspace, project, global_, builtin]:
        d.mkdir()

    return workspace, project, global_, builtin


def _make_skill(base: Path, name: str, description: str) -> None:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content)


class TestListSkills:
    def test_empty_loader(self):
        loader = SkillsLoader()
        assert loader.list_skills() == []

    def test_single_tier(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "my-skill", "A workspace skill")

        loader = SkillsLoader(workspace_skills=ws)
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].source == SkillSource.WORKSPACE

    def test_all_four_tiers(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "ws-skill", "workspace skill")
        _make_skill(proj, "proj-skill", "project skill")
        _make_skill(glob, "global-skill", "global skill")
        _make_skill(bi, "builtin-skill", "builtin skill")

        loader = SkillsLoader(
            workspace_skills=ws,
            project_skills=proj,
            global_skills=glob,
            builtin_skills=bi,
        )
        skills = loader.list_skills()
        assert len(skills) == 4
        names = {s.name for s in skills}
        assert names == {"ws-skill", "proj-skill", "global-skill", "builtin-skill"}

    def test_workspace_shadows_builtin(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "shared", "workspace version")
        _make_skill(bi, "shared", "builtin version")

        loader = SkillsLoader(workspace_skills=ws, builtin_skills=bi)
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].source == SkillSource.WORKSPACE
        assert skills[0].description == "workspace version"

    def test_project_shadows_global(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(proj, "shared", "project version")
        _make_skill(glob, "shared", "global version")

        loader = SkillsLoader(project_skills=proj, global_skills=glob)
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].source == SkillSource.PROJECT

    def test_invalid_skill_skipped(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        # Name with invalid chars
        skill_dir = ws / "bad name!"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: bad name!\ndescription: test\n---\n"
        )
        # Also add a valid one
        _make_skill(ws, "good-skill", "valid skill")

        loader = SkillsLoader(workspace_skills=ws)
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "good-skill"

    def test_missing_description_skipped(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        skill_dir = ws / "no-desc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: no-desc\n---\n# Body\n")

        loader = SkillsLoader(workspace_skills=ws)
        skills = loader.list_skills()
        assert len(skills) == 0

    def test_nonexistent_tier_ignored(self, tmp_path):
        loader = SkillsLoader(
            workspace_skills=tmp_path / "does-not-exist",
        )
        assert loader.list_skills() == []


class TestLoadSkill:
    def test_load_from_workspace(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "test-skill", "desc")

        loader = SkillsLoader(workspace_skills=ws)
        body, found = loader.load_skill("test-skill")
        assert found is True
        assert "# test-skill" in body
        # Frontmatter should be stripped
        assert "---" not in body

    def test_load_not_found(self):
        loader = SkillsLoader()
        body, found = loader.load_skill("nonexistent")
        assert found is False
        assert body == ""

    def test_priority_order(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "shared", "ws desc")
        _make_skill(bi, "shared", "builtin desc")

        loader = SkillsLoader(workspace_skills=ws, builtin_skills=bi)
        body, found = loader.load_skill("shared")
        assert found is True
        # Should get the workspace version (it has "# shared" with ws content)


class TestBuildSkillsSummary:
    def test_xml_output(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "alpha", "Alpha skill")
        _make_skill(bi, "beta", "Beta skill")

        loader = SkillsLoader(workspace_skills=ws, builtin_skills=bi)
        xml = loader.build_skills_summary()
        assert "<skills>" in xml
        assert "</skills>" in xml
        assert "<name>alpha</name>" in xml
        assert "<name>beta</name>" in xml
        assert "<source>workspace</source>" in xml
        assert "<source>builtin</source>" in xml

    def test_filter_names(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "alpha", "Alpha skill")
        _make_skill(ws, "beta", "Beta skill")

        loader = SkillsLoader(workspace_skills=ws)
        xml = loader.build_skills_summary(filter_names=["alpha"])
        assert "<name>alpha</name>" in xml
        assert "beta" not in xml

    def test_empty_returns_empty(self):
        loader = SkillsLoader()
        assert loader.build_skills_summary() == ""

    def test_xml_escaping(self, skill_dirs):
        ws, proj, glob, bi = skill_dirs
        _make_skill(ws, "test-skill", "Description with <special> & chars")

        loader = SkillsLoader(workspace_skills=ws)
        xml = loader.build_skills_summary()
        assert "&lt;special&gt;" in xml
        assert "&amp;" in xml
