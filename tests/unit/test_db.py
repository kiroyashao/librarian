from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from src.db.manager import DatabaseManager


@pytest.fixture
def db() -> DatabaseManager:
    """Provide a fresh in-memory DatabaseManager with tables created."""
    manager = DatabaseManager(":memory:")
    manager.initialize()
    return manager


class TestDatabaseInitialization:
    def test_tables_created(self, db: DatabaseManager) -> None:
        with db.get_connection() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "skills" in tables
        assert "skills_links" in tables
        assert "tools_ref_count" in tables

    def test_foreign_keys_enabled(self, db: DatabaseManager) -> None:
        with db.get_connection() as conn:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_initialize_idempotent(self, db: DatabaseManager) -> None:
        db.initialize()
        db.initialize()
        skills = db.get_all_skills()
        assert skills == []


class TestSkillCRUD:
    def test_upsert_and_get(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        result = db.get_skill("test_skill")
        assert result is not None
        assert result["skill_name"] == "test_skill"
        assert result["last_update_at"] is not None
        assert result["last_use_at"] is not None

    def test_upsert_with_timestamps(self, db: DatabaseManager) -> None:
        now = datetime.now(timezone.utc)
        db.upsert_skill("test_skill", last_update_at=now, last_use_at=now)
        result = db.get_skill("test_skill")
        assert result is not None
        assert result["last_update_at"] == now.isoformat()

    def test_upsert_updates_existing(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        later = datetime(2099, 1, 1, tzinfo=timezone.utc)
        db.upsert_skill("test_skill", last_update_at=later)
        result = db.get_skill("test_skill")
        assert result["last_update_at"] == later.isoformat()

    def test_get_nonexistent(self, db: DatabaseManager) -> None:
        assert db.get_skill("nope") is None

    def test_get_all_skills(self, db: DatabaseManager) -> None:
        db.upsert_skill("a")
        db.upsert_skill("b")
        all_skills = db.get_all_skills()
        names = {s["skill_name"] for s in all_skills}
        assert names == {"a", "b"}

    def test_delete_skill(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.delete_skill("test_skill")
        assert db.get_skill("test_skill") is None

    def test_update_skill_timestamps(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        later = datetime(2099, 6, 1, tzinfo=timezone.utc)
        db.update_skill_timestamps("test_skill", last_update_at=later)
        result = db.get_skill("test_skill")
        assert result["last_update_at"] == later.isoformat()

    def test_update_skill_timestamps_partial(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        original = db.get_skill("test_skill")
        later = datetime(2099, 6, 1, tzinfo=timezone.utc)
        db.update_skill_timestamps("test_skill", last_use_at=later)
        result = db.get_skill("test_skill")
        assert result["last_update_at"] == original["last_update_at"]
        assert result["last_use_at"] == later.isoformat()

    def test_search_skills(self, db: DatabaseManager) -> None:
        db.upsert_skill("data_analysis")
        db.upsert_skill("data_pipeline")
        db.upsert_skill("web_scraper")
        results = db.search_skills("data")
        names = {s["skill_name"] for s in results}
        assert names == {"data_analysis", "data_pipeline"}

    def test_search_skills_no_match(self, db: DatabaseManager) -> None:
        db.upsert_skill("data_analysis")
        results = db.search_skills("xyz")
        assert results == []


class TestSkillLinksCRUD:
    def test_add_and_get_links(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/agents/agent1")
        links = db.get_skill_links("test_skill")
        assert len(links) == 1
        assert links[0]["link_path"] == "/agents/agent1"

    def test_get_all_links(self, db: DatabaseManager) -> None:
        db.upsert_skill("s1")
        db.upsert_skill("s2")
        db.add_skill_link("s1", "/a1")
        db.add_skill_link("s2", "/a2")
        all_links = db.get_all_links()
        assert len(all_links) == 2

    def test_delete_skill_links(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/a1")
        db.add_skill_link("test_skill", "/a2")
        db.delete_skill_links("test_skill")
        assert db.get_skill_links("test_skill") == []

    def test_update_link_timestamp(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/a1")
        later = datetime(2099, 1, 1, tzinfo=timezone.utc)
        db.update_link_timestamp("test_skill", "/a1", later)
        links = db.get_skill_links("test_skill")
        assert links[0]["last_update_at"] == later.isoformat()

    def test_cascade_delete(self, db: DatabaseManager) -> None:
        db.upsert_skill("test_skill")
        db.add_skill_link("test_skill", "/a1")
        db.add_skill_link("test_skill", "/a2")
        db.delete_skill("test_skill")
        assert db.get_skill_links("test_skill") == []


class TestToolRefCountCRUD:
    def test_upsert_and_get(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 3)
        assert db.get_tool_ref("tool_a") == 3

    def test_upsert_updates_existing(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 3)
        db.upsert_tool_ref("tool_a", 5)
        assert db.get_tool_ref("tool_a") == 5

    def test_get_nonexistent(self, db: DatabaseManager) -> None:
        assert db.get_tool_ref("nope") is None

    def test_get_all_tools_refs(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 1)
        db.upsert_tool_ref("tool_b", 2)
        refs = db.get_all_tools_refs()
        names = {r["tool_name"] for r in refs}
        assert names == {"tool_a", "tool_b"}

    def test_increment_new_tool(self, db: DatabaseManager) -> None:
        db.increment_tool_ref("tool_a")
        assert db.get_tool_ref("tool_a") == 1

    def test_increment_existing_tool(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 3)
        db.increment_tool_ref("tool_a")
        assert db.get_tool_ref("tool_a") == 4

    def test_decrement_existing_tool(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 3)
        result = db.decrement_tool_ref("tool_a")
        assert result == 2
        assert db.get_tool_ref("tool_a") == 2

    def test_decrement_to_zero_deletes(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 1)
        result = db.decrement_tool_ref("tool_a")
        assert result == 0
        assert db.get_tool_ref("tool_a") is None

    def test_decrement_nonexistent(self, db: DatabaseManager) -> None:
        result = db.decrement_tool_ref("nope")
        assert result == 0

    def test_delete_tool_ref(self, db: DatabaseManager) -> None:
        db.upsert_tool_ref("tool_a", 5)
        db.delete_tool_ref("tool_a")
        assert db.get_tool_ref("tool_a") is None


class TestThreadSafety:
    def test_concurrent_upserts(self, db: DatabaseManager) -> None:
        errors: list[Exception] = []

        def worker(name: str) -> None:
            try:
                for i in range(10):
                    db.upsert_skill(f"{name}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        all_skills = db.get_all_skills()
        assert len(all_skills) == 40
