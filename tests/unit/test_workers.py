from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.schema import LibrarianConfig
from src.db.manager import DatabaseManager
from src.workers.base import BaseWorker
from src.workers.skill_deduplicator import SkillDeduplicator
from src.workers.skill_evaluator import SkillEvaluator
from src.workers.skill_link_maintainer import SkillLinkMaintainer
from src.workers.skill_pruner import SkillPruner
from src.workers.skill_router import SkillRouter
from src.workers.skill_splitter import SkillSplitter
from src.workers.tool_guardian import ToolGuardian
from src.workers.tool_synthesizer import ToolSynthesizer


def _make_config() -> LibrarianConfig:
    return LibrarianConfig()


class TestBaseWorker:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseWorker()

    def test_lazy_initialization(self) -> None:
        router = SkillRouter()
        assert router._initialized is False
        assert router._llm is None

    def test_ensure_initialized(self) -> None:
        router = SkillRouter()
        config = _make_config()
        router.ensure_initialized(config)
        assert router._initialized is True

    def test_ensure_initialized_idempotent(self) -> None:
        router = SkillRouter()
        config = _make_config()
        router.ensure_initialized(config)
        router.ensure_initialized(config)
        assert router._initialized is True


class TestSkillRouter:
    def test_route_evaluate_by_default(self) -> None:
        router = SkillRouter()
        config = _make_config()
        router.ensure_initialized(config)
        state = {
            "pending_skills": [{"name": "small_skill", "content": "short"}],
            "split_rule": {"max_lines": 1000},
        }
        result = router.execute(state)
        assert result["route_decisions"]["small_skill"] == "evaluate"

    def test_route_split_for_large_skill(self) -> None:
        router = SkillRouter()
        config = _make_config()
        router.ensure_initialized(config)
        large_content = "\n".join([f"line {i}" for i in range(1001)])
        state = {
            "pending_skills": [{"name": "big_skill", "content": large_content}],
            "split_rule": {"max_lines": 1000},
        }
        result = router.execute(state)
        assert result["route_decisions"]["big_skill"] == "split"

    def test_route_with_llm(self) -> None:
        router = SkillRouter()
        config = _make_config()
        router.ensure_initialized(config)
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "merge"
        mock_llm.invoke.return_value = mock_response
        router._llm = mock_llm
        state = {
            "pending_skills": [
                {"name": "skill_a", "content": "a"},
                {"name": "skill_b", "content": "b"},
            ],
            "split_rule": {"max_lines": 1000},
        }
        result = router.execute(state)
        assert result["route_decisions"]["skill_a"] == "merge"


class TestSkillEvaluator:
    def test_evaluate_with_no_llm(self) -> None:
        evaluator = SkillEvaluator()
        config = _make_config()
        evaluator.ensure_initialized(config)
        state = {
            "pending_skills": [{"name": "test", "content": "some content"}],
            "skills_dir": None,
            "tools_dir": None,
        }
        result = evaluator.execute(state)
        assert len(result["evaluation_results"]) == 1
        assert result["evaluation_results"][0]["confidence_score"] == 0.5

    def test_evaluate_with_llm(self) -> None:
        evaluator = SkillEvaluator()
        config = _make_config()
        evaluator.ensure_initialized(config)
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"score": 0.9, "categories": ["data_analysis"]}'
        mock_llm.invoke.return_value = mock_response
        evaluator._llm = mock_llm
        state = {
            "pending_skills": [{"name": "test", "content": "some content"}],
            "skills_dir": None,
            "tools_dir": None,
        }
        result = evaluator.execute(state)
        assert result["evaluation_results"][0]["confidence_score"] == 0.9
        assert result["evaluation_results"][0]["passed"] is True

    def test_evaluate_below_threshold(self) -> None:
        evaluator = SkillEvaluator()
        config = _make_config()
        evaluator.ensure_initialized(config)
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"score": 0.3, "categories": ["other"]}'
        mock_llm.invoke.return_value = mock_response
        evaluator._llm = mock_llm
        state = {
            "pending_skills": [{"name": "test", "content": "some content"}],
            "skills_dir": None,
            "tools_dir": None,
        }
        result = evaluator.execute(state)
        assert result["evaluation_results"][0]["passed"] is False


class TestSkillDeduplicator:
    def test_no_duplicates_single_skill(self) -> None:
        dedup = SkillDeduplicator()
        config = _make_config()
        dedup.ensure_initialized(config)
        state = {"pending_skills": [{"name": "only_one", "content": "x"}]}
        result = dedup.execute(state)
        assert result["merge_groups"] == []

    def test_duplicate_names(self) -> None:
        dedup = SkillDeduplicator()
        config = _make_config()
        dedup.ensure_initialized(config)
        state = {
            "pending_skills": [
                {"name": "same", "content": "a"},
                {"name": "same", "content": "b"},
            ]
        }
        result = dedup.execute(state)
        assert len(result["merge_groups"]) == 1
        assert "same" in result["merge_groups"][0]


class TestSkillSplitter:
    def test_split_large_skill(self) -> None:
        splitter = SkillSplitter()
        config = _make_config()
        splitter.ensure_initialized(config)
        large_content = "\n".join([f"line {i}" for i in range(1500)])
        state = {
            "pending_skills": [{"name": "big", "content": large_content}],
            "route_decisions": {"big": "split"},
        }
        result = splitter.execute(state)
        assert len(result["split_results"]) == 1
        assert "directory_skill" in result["split_results"][0]
        assert "sub_skills" in result["split_results"][0]

    def test_no_split_for_unrouted(self) -> None:
        splitter = SkillSplitter()
        config = _make_config()
        splitter.ensure_initialized(config)
        state = {
            "pending_skills": [{"name": "small", "content": "short"}],
            "route_decisions": {"small": "evaluate"},
        }
        result = splitter.execute(state)
        assert result["split_results"] == []


class TestSkillPruner:
    def test_find_expired_skills(self) -> None:
        pruner = SkillPruner()
        config = _make_config()
        pruner.ensure_initialized(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.upsert_skill("old_skill", last_use_at=old_date)
        state = {"db": db, "expiry_days": 90}
        result = pruner.execute(state)
        assert "old_skill" in result["expired_skills"]

    def test_no_expired_skills(self) -> None:
        pruner = SkillPruner()
        config = _make_config()
        pruner.ensure_initialized(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        db.upsert_skill("fresh_skill")
        state = {"db": db, "expiry_days": 90}
        result = pruner.execute(state)
        assert result["expired_skills"] == []

    def test_no_database(self) -> None:
        pruner = SkillPruner()
        config = _make_config()
        pruner.ensure_initialized(config)
        state = {}
        result = pruner.execute(state)
        assert result["expired_skills"] == []


class TestSkillLinkMaintainer:
    def test_update_links_after_removal(self) -> None:
        maintainer = SkillLinkMaintainer()
        config = _make_config()
        maintainer.ensure_initialized(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        db.upsert_skill("removed_skill")
        db.add_skill_link("removed_skill", "/agents/a1")
        state = {"db": db, "removed_skills": ["removed_skill"]}
        result = maintainer.execute(state)
        assert result["link_updates"]["removed"] == 1

    def test_update_links_after_split(self) -> None:
        maintainer = SkillLinkMaintainer()
        config = _make_config()
        maintainer.ensure_initialized(config)
        db = DatabaseManager(":memory:")
        db.initialize()
        db.upsert_skill("parent_skill")
        db.upsert_skill("parent_skill_part1")
        state = {
            "db": db,
            "split_results": [
                {
                    "directory_skill": {"name": "parent_skill"},
                    "sub_skills": [{"name": "parent_skill_part1"}],
                }
            ],
        }
        result = maintainer.execute(state)
        assert result["link_updates"]["added"] == 1


class TestToolSynthesizer:
    def test_create_fallback_tool(self, tmp_path: Path) -> None:
        synthesizer = ToolSynthesizer()
        config = _make_config()
        synthesizer.ensure_initialized(config)
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        state = {
            "missing_tools": ["tool_data_analyzer"],
            "tools_dir": str(tools_dir),
        }
        result = synthesizer.execute(state)
        assert len(result["created_tools"]) == 1
        assert (tools_dir / "tool_data_analyzer").exists()

    def test_no_missing_tools(self) -> None:
        synthesizer = ToolSynthesizer()
        config = _make_config()
        synthesizer.ensure_initialized(config)
        state = {"missing_tools": []}
        result = synthesizer.execute(state)
        assert result["created_tools"] == []


class TestToolGuardian:
    def test_auto_review_approve(self) -> None:
        guardian = ToolGuardian()
        config = _make_config()
        config.workers.tool_guardian.require_human_review = False
        guardian.ensure_initialized(config)
        guardian._require_human_review = False
        state = {
            "created_tools": [{"name": "tool_test_func", "path": "/nonexistent"}],
        }
        result = guardian.execute(state)
        assert result["review_results"][0]["status"] == "approved"

    def test_auto_review_reject_bad_name(self) -> None:
        guardian = ToolGuardian()
        config = _make_config()
        config.workers.tool_guardian.require_human_review = False
        guardian.ensure_initialized(config)
        guardian._require_human_review = False
        state = {
            "created_tools": [{"name": "bad_tool_name", "path": "/nonexistent"}],
        }
        result = guardian.execute(state)
        assert result["review_results"][0]["status"] == "rejected"

    def test_human_review_mode(self) -> None:
        guardian = ToolGuardian()
        config = _make_config()
        config.workers.tool_guardian.require_human_review = True
        guardian.ensure_initialized(config)
        guardian._require_human_review = True
        state = {
            "created_tools": [{"name": "tool_test_func", "path": "/nonexistent"}],
        }
        result = guardian.execute(state)
        assert result["review_results"][0]["status"] == "pending_human_review"
        assert "pending_human_reviews" in result

    def test_submit_human_review(self) -> None:
        guardian = ToolGuardian()
        config = _make_config()
        guardian.ensure_initialized(config)
        guardian._pending_reviews = {"tool_test": "/api/reviews/tools/tool_test"}
        result = guardian.submit_human_review("tool_test", True)
        assert result["status"] == "approved"
        assert "tool_test" not in guardian._pending_reviews
