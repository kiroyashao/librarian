from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.db.manager import DatabaseManager
from src.models.file_io import write_skill_file
from src.models.skill import SkillFile, SkillFrontmatter
from src.tools.builtin import (
    CheckSkillLinksTool,
    GetSkillLinksTool,
    MergeSkillsTool,
    PushSkillsTool,
    RemoveSkillsTool,
    UpdateSkillFrontmatterTool,
)


@pytest.fixture
def db() -> DatabaseManager:
    manager = DatabaseManager(":memory:")
    manager.initialize()
    return manager


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def tools_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tools"
    d.mkdir()
    return d


def _write_skill(skills_dir: Path, name: str, content: str = "") -> None:
    sf = SkillFile(frontmatter=SkillFrontmatter(name=name), content=content)
    write_skill_file(skills_dir / f"{name}.md", sf)


class TestUpdateSkillFrontmatterTool:
    def test_update_confidence_score(self, db: DatabaseManager, skills_dir: Path) -> None:
        _write_skill(skills_dir, "test_skill")
        db.upsert_skill("test_skill")
        tool = UpdateSkillFrontmatterTool(db, skills_dir)
        result = tool.run("test_skill", confidence_score=0.9)
        assert result["status"] == "updated"
        assert result["frontmatter"]["metadata"]["confidence_score"] == 0.9

    def test_update_categories(self, db: DatabaseManager, skills_dir: Path) -> None:
        _write_skill(skills_dir, "test_skill")
        db.upsert_skill("test_skill")
        tool = UpdateSkillFrontmatterTool(db, skills_dir)
        result = tool.run("test_skill", categories=["data_analysis"])
        assert result["frontmatter"]["metadata"]["categories"] == ["data_analysis"]

    def test_update_increments_update_times(self, db: DatabaseManager, skills_dir: Path) -> None:
        _write_skill(skills_dir, "test_skill")
        db.upsert_skill("test_skill")
        tool = UpdateSkillFrontmatterTool(db, skills_dir)
        tool.run("test_skill", confidence_score=0.5)
        result = tool.run("test_skill", confidence_score=0.8)
        assert result["frontmatter"]["metadata"]["update_times"] == 2

    def test_skill_not_found(self, db: DatabaseManager, skills_dir: Path) -> None:
        tool = UpdateSkillFrontmatterTool(db, skills_dir)
        with pytest.raises(FileNotFoundError):
            tool.run("nonexistent")


class TestCheckSkillLinksTool:
    def test_valid_skill_links(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "sub_skill")
        _write_skill(skills_dir, "main", "[[skills: sub_skill]]")
        db.upsert_skill("main")
        tool = CheckSkillLinksTool(db, skills_dir, tools_dir)
        result = tool.run("main")
        assert "skills:sub_skill" in result["valid"]
        assert result["broken"] == []

    def test_broken_skill_links(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "main", "[[skills: missing]]")
        db.upsert_skill("main")
        tool = CheckSkillLinksTool(db, skills_dir, tools_dir)
        result = tool.run("main")
        assert "skills:missing" in result["broken"]

    def test_valid_tool_links(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        (tools_dir / "analyzer.sh").write_text("#!/bin/bash")
        _write_skill(skills_dir, "main", "[[tools: analyzer.sh]]")
        db.upsert_skill("main")
        tool = CheckSkillLinksTool(db, skills_dir, tools_dir)
        result = tool.run("main")
        assert "tools:analyzer.sh" in result["valid"]

    def test_broken_tool_links(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "main", "[[tools: missing.sh]]")
        db.upsert_skill("main")
        tool = CheckSkillLinksTool(db, skills_dir, tools_dir)
        result = tool.run("main")
        assert "tools:missing.sh" in result["broken"]

    def test_skill_not_found(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        tool = CheckSkillLinksTool(db, skills_dir, tools_dir)
        result = tool.run("nonexistent")
        assert result.get("error") == "skill not found"


class TestMergeSkillsTool:
    def test_merge_two_skills(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "skill_a", "Content A")
        _write_skill(skills_dir, "skill_b", "Content B")
        db.upsert_skill("skill_a")
        db.upsert_skill("skill_b")
        tool = MergeSkillsTool(db, skills_dir, tools_dir)
        result = tool.run("merged", ["skill_a", "skill_b"], "Merged content")
        assert result["status"] == "merged"
        assert result["target"] == "merged"
        assert not (skills_dir / "skill_a.md").exists()
        assert not (skills_dir / "skill_b.md").exists()
        assert (skills_dir / "merged.md").exists()

    def test_merge_preserves_tool_refs(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "skill_a", "[[tools: analyzer.sh]]")
        _write_skill(skills_dir, "skill_b", "[[tools: analyzer.sh]]")
        db.upsert_skill("skill_a")
        db.upsert_skill("skill_b")
        tool = MergeSkillsTool(db, skills_dir, tools_dir)
        result = tool.run("merged", ["skill_a", "skill_b"], "Merged")
        assert result["status"] == "merged"


class TestRemoveSkillsTool:
    def test_remove_skill(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "test_skill")
        db.upsert_skill("test_skill")
        tool = RemoveSkillsTool(db, skills_dir, tools_dir)
        result = tool.run(["test_skill"])
        assert "test_skill" in result["removed_skills"]
        assert not (skills_dir / "test_skill.md").exists()
        assert db.get_skill("test_skill") is None

    def test_remove_skill_decrements_tool_ref(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        _write_skill(skills_dir, "test_skill", "[[tools: analyzer.sh]]")
        db.upsert_skill("test_skill")
        db.upsert_tool_ref("analyzer.sh", 2)
        tool = RemoveSkillsTool(db, skills_dir, tools_dir)
        result = tool.run(["test_skill"])
        assert db.get_tool_ref("analyzer.sh") == 1

    def test_remove_skill_deletes_zero_ref_tool(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        tool_file = tools_dir / "analyzer.sh"
        tool_file.write_text("#!/bin/bash")
        _write_skill(skills_dir, "test_skill", "[[tools: analyzer.sh]]")
        db.upsert_skill("test_skill")
        db.upsert_tool_ref("analyzer.sh", 1)
        tool = RemoveSkillsTool(db, skills_dir, tools_dir)
        result = tool.run(["test_skill"])
        assert "analyzer.sh" in result["removed_tools"]
        assert not tool_file.exists()
        assert db.get_tool_ref("analyzer.sh") is None


class TestGetSkillLinksTool:
    def test_get_links(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/agents/a1")
        tool = GetSkillLinksTool(db)
        result = tool.run("test_skill")
        assert result["skill_name"] == "test_skill"
        assert len(result["links"]) == 1

    def test_get_links_empty(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        tool = GetSkillLinksTool(db)
        result = tool.run("test_skill")
        assert result["links"] == []


class TestPushSkillsTool:
    def test_push_new_skill(self, db: DatabaseManager, skills_dir: Path) -> None:
        tool = PushSkillsTool(db, skills_dir)
        result = tool.run("new_skill", "Hello world", description="A new skill")
        assert result["status"] == "pushed"
        assert (skills_dir / "new_skill.md").exists()
        assert db.get_skill("new_skill") is not None

    def test_push_existing_skill_updates_content(self, db: DatabaseManager, skills_dir: Path) -> None:
        _write_skill(skills_dir, "existing", "Old content")
        db.upsert_skill("existing")
        tool = PushSkillsTool(db, skills_dir)
        result = tool.run("existing", "New content")
        assert result["status"] == "pushed"

    def test_push_with_link(self, db: DatabaseManager, skills_dir: Path) -> None:
        tool = PushSkillsTool(db, skills_dir)
        result = tool.run("linked_skill", "Content", link_path="/agents/a1")
        assert result["status"] == "pushed"
        links = db.get_skill_links("linked_skill")
        assert len(links) == 1
