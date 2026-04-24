from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config.schema import LibrarianConfig
from src.db.manager import DatabaseManager
from src.workflows.workflows import Case1Workflow, Case2Workflow, Case3Workflow


def _make_config() -> LibrarianConfig:
    return LibrarianConfig()


class TestCase1Workflow:
    def test_build_graph(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        graph = workflow.build_graph()
        assert graph is not None

    def test_route_node(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {
            "pending_skills": [{"name": "test", "content": "short"}],
        }
        result = workflow.route_node(state)
        assert "route_decisions" in result

    def test_should_deduplicate_merge(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"route_decisions": {"skill_a": "merge"}}
        assert workflow.should_deduplicate(state) == "deduplicate"

    def test_should_deduplicate_no_merge(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"route_decisions": {"skill_a": "split"}}
        assert workflow.should_deduplicate(state) == "check_split"

    def test_should_split(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"route_decisions": {"skill_a": "split"}}
        assert workflow.should_split(state) == "split"

    def test_should_not_split(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"route_decisions": {"skill_a": "evaluate"}}
        assert workflow.should_split(state) == "evaluate"

    def test_should_create_tools(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"missing_tools": ["tool_x"]}
        assert workflow.should_create_tools(state) == "create_tools"

    def test_should_not_create_tools(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"missing_tools": []}
        assert workflow.should_create_tools(state) == "commit"

    def test_should_commit_or_rollback_commit(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"evaluation_results": [{"skill_name": "test", "passed": True}]}
        assert workflow.should_commit_or_rollback(state) == "commit"

    def test_should_commit_or_rollback_rollback(self) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        state = {"evaluation_results": [{"skill_name": "test", "passed": False}]}
        assert workflow.should_commit_or_rollback(state) == "rollback"

    def test_full_case1_evaluate_path(self, tmp_path: Path) -> None:
        config = _make_config()
        workflow = Case1Workflow(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        state = {
            "pending_skills": [{"name": "simple_skill", "content": "simple"}],
            "db": db,
            "skills_dir": str(skills_dir),
            "tools_dir": str(tmp_path / "tools"),
        }
        result = workflow.route_node(state)
        assert result["route_decisions"]["simple_skill"] == "evaluate"


class TestCase2Workflow:
    def test_build_graph(self) -> None:
        config = _make_config()
        workflow = Case2Workflow(config)
        graph = workflow.build_graph()
        assert graph is not None

    def test_deduplicate_node(self) -> None:
        config = _make_config()
        workflow = Case2Workflow(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        state = {
            "db": db,
            "skills_dir": None,
            "pending_skills": [{"name": "a", "content": "x"}],
        }
        result = workflow.deduplicate_node(state)
        assert "merge_groups" in result

    def test_maintain_links_node(self) -> None:
        config = _make_config()
        workflow = Case2Workflow(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        state = {"db": db}
        result = workflow.maintain_links_node(state)
        assert "link_updates" in result


class TestCase3Workflow:
    def test_build_graph(self) -> None:
        config = _make_config()
        workflow = Case3Workflow(config)
        graph = workflow.build_graph()
        assert graph is not None

    def test_prune_node(self) -> None:
        config = _make_config()
        workflow = Case3Workflow(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        db.upsert_skill("fresh_skill")
        state = {"db": db, "expiry_days": 90}
        result = workflow.prune_node(state)
        assert "expired_skills" in result

    def test_maintain_links_node(self) -> None:
        config = _make_config()
        workflow = Case3Workflow(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        state = {"db": db, "expired_skills": []}
        result = workflow.maintain_links_node(state)
        assert "link_updates" in result
