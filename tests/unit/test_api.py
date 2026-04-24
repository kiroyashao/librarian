from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config.schema import LibrarianConfig
from src.db.manager import DatabaseManager
from src.git_manager.manager import GitManager
from src.git_manager.tmp_manager import TmpManager
from src.models.file_io import write_skill_file
from src.models.skill import SkillFile, SkillFrontmatter
from src.workflows.human_review import HumanReviewManager


@pytest.fixture
def app_setup(tmp_path: Path):
    config = LibrarianConfig()
    db = DatabaseManager(":memory:")
    db.initialize()
    skills_dir = tmp_path / "skills"
    tools_dir = tmp_path / "tools"
    skills_dir.mkdir()
    tools_dir.mkdir()
    git_dir = tmp_path / "repo"
    git_dir.mkdir()
    git_manager = GitManager(git_dir)
    git_manager.init()
    (git_dir / ".gitkeep").write_text("")
    git_manager.add()
    git_manager.commit("Initial commit")
    tmp_manager = TmpManager(git_dir)
    human_review_mgr = HumanReviewManager()

    from src.config.loader import ConfigLoader
    config_loader = ConfigLoader.__new__(ConfigLoader)

    app = create_app(
        config=config,
        config_loader=config_loader,
        db=db,
        git_manager=git_manager,
        tmp_manager=tmp_manager,
        human_review_manager=human_review_mgr,
        skills_dir=skills_dir,
        tools_dir=tools_dir,
    )
    client = TestClient(app)
    return client, db, skills_dir, tools_dir, human_review_mgr


class TestSkillsAPI:
    def test_get_skills_empty(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.get("/skills")
        assert response.status_code == 200
        assert response.json() == []

    def test_submit_skill(self, app_setup) -> None:
        client, db, *_ = app_setup
        response = client.post("/skills", json={
            "name": "test_skill",
            "content": "Test content",
            "description": "A test skill",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "pushed"

    def test_get_skill(self, app_setup) -> None:
        client, db, skills_dir, *_ = app_setup
        sf = SkillFile(frontmatter=SkillFrontmatter(name="test_skill"), content="Hello")
        write_skill_file(skills_dir / "test_skill.md", sf)
        db.upsert_skill("test_skill")
        response = client.get("/skills/test_skill")
        assert response.status_code == 200
        data = response.json()
        assert data["record"]["skill_name"] == "test_skill"

    def test_get_skill_not_found(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.get("/skills/nonexistent")
        assert response.status_code == 404

    def test_delete_skill(self, app_setup) -> None:
        client, db, skills_dir, tools_dir, _ = app_setup
        sf = SkillFile(frontmatter=SkillFrontmatter(name="del_skill"), content="Bye")
        write_skill_file(skills_dir / "del_skill.md", sf)
        db.upsert_skill("del_skill")
        response = client.delete("/skills/del_skill")
        assert response.status_code == 200

    def test_search_skills(self, app_setup) -> None:
        client, db, *_ = app_setup
        db.upsert_skill("data_analysis")
        db.upsert_skill("web_scraper")
        response = client.get("/skills/search?q=data")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1
        assert results[0]["skill_name"] == "data_analysis"

    def test_get_skill_links(self, app_setup) -> None:
        client, db, *_ = app_setup
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/agents/a1")
        response = client.get("/skills/test_skill/links")
        assert response.status_code == 200
        data = response.json()
        assert len(data["links"]) == 1


class TestGitAPI:
    def test_get_git_history(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.get("/git/history")
        assert response.status_code == 200

    def test_rollback_invalid_commit(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.post("/git/rollback/invalid_hash")
        assert response.status_code == 400


class TestConfigAPI:
    def test_get_config(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.get("/config")
        assert response.status_code == 200
        data = response.json()
        assert "api" in data
        assert "database" in data


class TestToolsAPI:
    def test_get_tools_empty(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.get("/tools")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_tools_with_refs(self, app_setup) -> None:
        client, db, *_ = app_setup
        db.upsert_tool_ref("analyzer.sh", 3)
        response = client.get("/tools")
        assert response.status_code == 200
        results = response.json()
        assert len(results) == 1


class TestReviewsAPI:
    def test_get_pending_reviews(self, app_setup) -> None:
        client, _, _, _, hrm = app_setup
        hrm.create_review("tool_test")
        response = client.get("/reviews")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_submit_review(self, app_setup) -> None:
        client, _, _, _, hrm = app_setup
        review = hrm.create_review("tool_test")
        review_id = review["review_id"]
        response = client.post(f"/reviews/{review_id}", json={
            "approved": True,
            "comment": "Looks good",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_submit_review_not_found(self, app_setup) -> None:
        client, *_ = app_setup
        response = client.post("/reviews/nonexistent", json={
            "approved": True,
        })
        assert response.status_code == 404
