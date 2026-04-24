from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillEvaluator(BaseWorker):
    """Evaluates skills by scoring, classifying, and checking references.

    Uses LLM to assign confidence scores and categories. Checks that
    referenced tools and sub-skills exist.

    Attributes:
        _quality_threshold: Minimum score for a skill to pass.
        _require_human_review: Whether human review is required.
        _categories: Valid category labels.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.skill_evaluator.llm
        self._quality_threshold = config.workers.skill_evaluator.quality_threshold
        self._require_human_review = config.workers.skill_evaluator.require_human_review
        self._categories = config.workers.skill_evaluator.categories
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.skill_evaluator.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Evaluate skills and determine if they pass quality checks.

        Args:
            state: Workflow state with 'pending_skills' list.

        Returns:
            Updated state with 'evaluation_results', 'missing_tools',
            'missing_skills', and 'rejected_skills' keys.
        """
        pending_skills: list[dict] = state.get("pending_skills", [])
        evaluation_results: list[dict] = []
        missing_tools: list[str] = []
        missing_skills: list[str] = []
        rejected_skills: list[str] = []

        skills_dir = state.get("skills_dir")
        tools_dir = state.get("tools_dir")

        for skill_data in pending_skills:
            skill_name = skill_data.get("name", "unknown")
            content = skill_data.get("content", "")

            score, categories = self._evaluate_skill(skill_name, content)

            missing = self._check_references(content, skills_dir, tools_dir)
            missing_tools.extend(missing.get("tools", []))
            missing_skills.extend(missing.get("skills", []))

            result = {
                "skill_name": skill_name,
                "confidence_score": score,
                "categories": categories,
                "passed": score >= self._quality_threshold,
            }
            evaluation_results.append(result)

            if not result["passed"]:
                rejection_count = state.get("rejection_counts", {}).get(skill_name, 0) + 1
                max_rejections = state.get("max_rejection_count", 3)
                if rejection_count >= max_rejections:
                    rejected_skills.append(skill_name)
                else:
                    rejected = state.get("rejected_for_reroute", [])
                    rejected.append(skill_name)
                    state["rejected_for_reroute"] = rejected

        state["evaluation_results"] = evaluation_results
        state["missing_tools"] = list(set(missing_tools))
        state["missing_skills"] = list(set(missing_skills))
        state["rejected_skills"] = rejected_skills
        return state

    def _evaluate_skill(self, skill_name: str, content: str) -> tuple[float, list[str]]:
        """Score and categorize a skill using LLM.

        Args:
            skill_name: Name of the skill.
            content: The skill's markdown content.

        Returns:
            A tuple of (confidence_score, categories).
        """
        if self._llm is None:
            return 0.5, ["other"]

        prompt = (
            f"Evaluate this skill named '{skill_name}':\n\n"
            f"{content[:2000]}\n\n"
            f"Return a JSON object with 'score' (0.0-1.0) and 'categories' (list of strings).\n"
            f"Valid categories: {self._categories or ['other']}"
        )
        try:
            import json
            response = self._llm.invoke(prompt)
            data = json.loads(response.content)
            score = float(data.get("score", 0.5))
            categories = data.get("categories", ["other"])
            return score, categories
        except Exception:
            return 0.5, ["other"]

    def _check_references(
        self, content: str, skills_dir: Any, tools_dir: Any
    ) -> dict[str, list[str]]:
        """Check if referenced skills and tools exist.

        Args:
            content: The skill's markdown content.
            skills_dir: Path to the skills directory (or None).
            tools_dir: Path to the tools directory (or None).

        Returns:
            A dict with 'tools' and 'skills' lists of missing references.
        """
        from src.models.skill import _REF_PATTERN

        missing: dict[str, list[str]] = {"tools": [], "skills": []}
        for match in _REF_PATTERN.finditer(content):
            ref_type, ref_name = match.group(1), match.group(2)
            if ref_type == "skills" and skills_dir:
                from pathlib import Path
                if not (Path(skills_dir) / f"{ref_name}.md").exists():
                    missing["skills"].append(ref_name)
            elif ref_type == "tools" and tools_dir:
                from pathlib import Path
                if not (Path(tools_dir) / ref_name).exists():
                    missing["tools"].append(ref_name)
        return missing
