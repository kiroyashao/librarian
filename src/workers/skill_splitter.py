from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class SkillSplitter(BaseWorker):
    """Splits large skills into a directory skill and sub-skills.

    Uses LLM to determine split points when a skill exceeds max_lines.
    The original skill becomes a "table of contents" and sub-skills
    become "chapters".

    Attributes:
        _max_lines: Maximum lines before a skill should be split.
        _min_lines: Minimum lines for a sub-skill chunk.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.skill_splitter.llm
        self._max_lines = config.workers.skill_splitter.split_rule.max_lines
        self._min_lines = config.workers.skill_splitter.split_rule.min_lines
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.skill_splitter.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Split oversized skills into directory + sub-skills.

        Args:
            state: Workflow state with 'pending_skills' and 'route_decisions'.

        Returns:
            Updated state with 'split_results' containing the directory
            skill and its sub-skills.
        """
        pending_skills: list[dict] = state.get("pending_skills", [])
        route_decisions: dict[str, str] = state.get("route_decisions", {})
        split_results: list[dict] = []

        for skill_data in pending_skills:
            skill_name = skill_data.get("name", "unknown")
            if route_decisions.get(skill_name) != "split":
                continue

            content = skill_data.get("content", "")
            line_count = content.count("\n") + 1 if content else 0

            if line_count <= self._max_lines:
                continue

            result = self._split_skill(skill_name, content)
            split_results.append(result)

        state["split_results"] = split_results
        return state

    def _split_skill(self, skill_name: str, content: str) -> dict[str, Any]:
        """Split a single skill into directory + sub-skills.

        Args:
            skill_name: Name of the skill to split.
            content: The full markdown content.

        Returns:
            A dict with 'directory_skill' and 'sub_skills' keys.
        """
        lines = content.split("\n")
        total_lines = len(lines)

        if self._llm:
            return self._llm_split(skill_name, content, lines)

        chunk_size = max(self._min_lines, total_lines // max(1, total_lines // self._max_lines))
        chunks: list[dict[str, str]] = []
        sub_names: list[str] = []

        for i, start in enumerate(range(0, total_lines, chunk_size)):
            chunk_lines = lines[start : start + chunk_size]
            sub_name = f"{skill_name}_part{i + 1}"
            sub_names.append(sub_name)
            chunks.append({
                "name": sub_name,
                "content": "\n".join(chunk_lines),
            })

        directory_content = f"## 任务目标\n\n本技能已拆分为以下子技能：\n\n"
        for sub_name in sub_names:
            directory_content += f"- [[skills: {sub_name}]]\n"

        return {
            "directory_skill": {"name": skill_name, "content": directory_content},
            "sub_skills": chunks,
        }

    def _llm_split(
        self, skill_name: str, content: str, lines: list[str]
    ) -> dict[str, Any]:
        """Use LLM to determine split points.

        Args:
            skill_name: Name of the skill.
            content: The full content.
            lines: The content split into lines.

        Returns:
            A dict with 'directory_skill' and 'sub_skills' keys.
        """
        if self._llm is None:
            return {"directory_skill": {"name": skill_name, "content": content}, "sub_skills": []}

        prompt = (
            f"Split this skill '{skill_name}' into logical sub-skills.\n"
            f"The skill has {len(lines)} lines (max allowed: {self._max_lines}).\n"
            f"Each sub-skill should have at least {self._min_lines} lines.\n"
            f"Return a JSON object with 'directory_content' (string) and 'sub_skills' "
            f"(list of objects with 'name' and 'content' keys).\n"
            f"The directory content should reference sub-skills using [[skills: name]] syntax.\n\n"
            f"Skill content:\n{content[:4000]}"
        )
        try:
            import json
            response = self._llm.invoke(prompt)
            data = json.loads(response.content)
            return {
                "directory_skill": {
                    "name": skill_name,
                    "content": data.get("directory_content", content),
                },
                "sub_skills": data.get("sub_skills", []),
            }
        except Exception:
            return {"directory_skill": {"name": skill_name, "content": content}, "sub_skills": []}
