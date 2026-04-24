from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillRouter(BaseWorker):
    """Determines whether skills need merging, splitting, or direct evaluation.

    Uses LLM to analyze incoming skills and route them to the appropriate
    downstream worker.

    Attributes:
        _llm: The LangChain ChatOpenAI instance for routing decisions.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration and update LLM reference.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.skill_router.llm
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.skill_router.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Route skills to the appropriate processing pipeline.

        Analyzes each skill and determines whether it should be merged,
        split, or sent directly to the evaluator.

        Args:
            state: Workflow state with 'pending_skills' list.

        Returns:
            Updated state with 'route_decisions' mapping skill names
            to actions: 'merge', 'split', or 'evaluate'.
        """
        pending_skills: list[dict] = state.get("pending_skills", [])
        decisions: dict[str, str] = {}

        for skill_data in pending_skills:
            skill_name = skill_data.get("name", "unknown")
            content = skill_data.get("content", "")
            line_count = content.count("\n") + 1 if content else 0

            split_rule = state.get("split_rule", {})
            max_lines = split_rule.get("max_lines", 1000)

            if self._llm and len(pending_skills) > 1:
                decisions[skill_name] = self._llm_route(skill_name, pending_skills)
            elif line_count > max_lines:
                decisions[skill_name] = "split"
            else:
                decisions[skill_name] = "evaluate"

        state["route_decisions"] = decisions
        return state

    def _llm_route(self, skill_name: str, all_skills: list[dict]) -> str:
        """Use LLM to determine routing for a skill.

        Args:
            skill_name: Name of the skill to route.
            all_skills: All pending skills for context.

        Returns:
            One of 'merge', 'split', or 'evaluate'.
        """
        if self._llm is None:
            return "evaluate"

        names = [s.get("name", "") for s in all_skills]
        prompt = (
            f"Given these skills: {names}\n"
            f"Should the skill '{skill_name}' be merged with another, split into smaller parts, or evaluated as-is?\n"
            f"Reply with exactly one word: merge, split, or evaluate"
        )
        try:
            response = self._llm.invoke(prompt)
            text = response.content.strip().lower()
            if text in ("merge", "split", "evaluate"):
                return text
        except Exception:
            pass
        return "evaluate"
