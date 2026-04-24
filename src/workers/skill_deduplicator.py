from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillDeduplicator(BaseWorker):
    """Merges duplicate or highly similar skills.

    Uses LLM to identify similar skills and produce merged content.

    Attributes:
        _llm: The LangChain ChatOpenAI instance for similarity analysis.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.skill_deduplicator.llm
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.skill_deduplicator.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Find and merge duplicate skills.

        Args:
            state: Workflow state with 'pending_skills' list.

        Returns:
            Updated state with 'merge_groups' — groups of skill names
            that should be merged together.
        """
        pending_skills: list[dict] = state.get("pending_skills", [])
        merge_groups: list[list[str]] = []

        if len(pending_skills) < 2:
            state["merge_groups"] = merge_groups
            return state

        if self._llm:
            merge_groups = self._llm_find_duplicates(pending_skills)
        else:
            seen_names: dict[str, list[str]] = {}
            for skill_data in pending_skills:
                name = skill_data.get("name", "").lower()
                if name in seen_names:
                    seen_names[name].append(skill_data.get("name", ""))
                else:
                    seen_names[name] = [skill_data.get("name", "")]
            merge_groups = [group for group in seen_names.values() if len(group) > 1]

        state["merge_groups"] = merge_groups
        return state

    def _llm_find_duplicates(self, skills: list[dict]) -> list[list[str]]:
        """Use LLM to identify duplicate skills.

        Args:
            skills: List of skill data dicts.

        Returns:
            Groups of skill names that should be merged.
        """
        if self._llm is None:
            return []

        names = [s.get("name", "") for s in skills]
        prompt = (
            f"Given these skills: {names}\n"
            f"Identify groups of skills that are duplicates or very similar and should be merged.\n"
            f"Return a JSON list of lists, where each inner list contains skill names to merge.\n"
            f"If no duplicates, return []."
        )
        try:
            import json
            response = self._llm.invoke(prompt)
            groups = json.loads(response.content)
            if isinstance(groups, list):
                return [g for g in groups if isinstance(g, list) and len(g) > 1]
        except Exception:
            pass
        return []
