from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillPruner(BaseWorker):
    """Cleans up skills that have not been used for a long time.

    Determines which skills are expired based on last_use_at timestamp
    and marks them for removal.

    Attributes:
        _expiry_days: Number of days after which a skill is considered expired.
    """

    DEFAULT_EXPIRY_DAYS: int = 90

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._expiry_days = config.workers.skill_pruner.get("expiry_days") or self.DEFAULT_EXPIRY_DAYS
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        pass

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Identify expired skills for cleanup.

        Args:
            state: Workflow state with 'db' (DatabaseManager) key.

        Returns:
            Updated state with 'expired_skills' list of skill names.
        """
        from src.db.manager import DatabaseManager

        db: DatabaseManager | None = state.get("db")
        if db is None:
            state["expired_skills"] = []
            return state

        all_skills = db.get_all_skills()
        now = datetime.now(timezone.utc)
        expired: list[str] = []

        for skill in all_skills:
            last_use = skill.get("last_use_at")
            if last_use is None:
                continue
            try:
                last_use_dt = datetime.fromisoformat(last_use)
                if (now - last_use_dt).days > self._expiry_days:
                    expired.append(skill["skill_name"])
            except (ValueError, TypeError):
                continue

        state["expired_skills"] = expired
        return state
