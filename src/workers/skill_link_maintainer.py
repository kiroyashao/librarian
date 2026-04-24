from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillLinkMaintainer(BaseWorker):
    """Maintains link relationships when skills are modified.

    Updates the skills_links table after cleanup, merge, or split
    operations change the skill graph.

    Attributes:
        _llm: The LangChain ChatOpenAI instance for link analysis.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.skill_link_maintainer.llm
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.skill_link_maintainer.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Update link relationships after skill modifications.

        Processes removed, merged, and split skills to ensure
        the skills_links table is consistent.

        Args:
            state: Workflow state with 'db', 'removed_skills',
                'merged_skills', 'split_results' keys.

        Returns:
            Updated state with 'link_updates' summary.
        """
        from src.db.manager import DatabaseManager

        db: DatabaseManager | None = state.get("db")
        if db is None:
            state["link_updates"] = {"error": "no database"}
            return state

        updates: dict[str, Any] = {"removed": 0, "added": 0}

        removed: list[str] = state.get("removed_skills", []) + state.get("expired_skills", [])
        for skill_name in removed:
            db.delete_skill_links(skill_name)
            updates["removed"] += 1

        merged: list[dict] = state.get("merge_results", [])
        for merge_result in merged:
            target = merge_result.get("target", "")
            sources = merge_result.get("sources_removed", [])
            for source in sources:
                old_links = db.get_skill_links(source) if db.get_skill(source) else []
                for link in old_links:
                    db.add_skill_link(target, link["link_path"])
                    updates["added"] += 1

        split_results: list[dict] = state.get("split_results", [])
        for split_result in split_results:
            directory = split_result.get("directory_skill", {}).get("name", "")
            sub_skills = split_result.get("sub_skills", [])
            for sub in sub_skills:
                sub_name = sub.get("name", "")
                if sub_name:
                    db.add_skill_link(sub_name, f"parent:{directory}")
                    updates["added"] += 1

        state["link_updates"] = updates
        return state
