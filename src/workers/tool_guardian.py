from __future__ import annotations

from typing import Any

from src.config.schema import LibrarianConfig
from src.workers.base import BaseWorker


class ToolGuardian(BaseWorker):
    """Reviews tools for security and correctness.

    When requireHumanReview is true, generates a review API endpoint
    instead of blocking. Otherwise uses LLM for automated review.

    Attributes:
        _require_human_review: Whether human review is required.
        _pending_reviews: Dict mapping tool names to review API paths.
    """

    def load_config(self, config: LibrarianConfig) -> None:
        """Receive new configuration.

        Args:
            config: The newly loaded LibrarianConfig.
        """
        self._llm_config_name = config.workers.tool_guardian.llm
        self._require_human_review = config.workers.tool_guardian.require_human_review
        self._config_pending = True

    def _on_initialize(self, config: LibrarianConfig) -> None:
        llm_name = config.workers.tool_guardian.llm
        if llm_name:
            llm_cfg = config.get_llm(llm_name)
            if llm_cfg:
                self._llm = self._create_llm(llm_cfg)
        self._pending_reviews: dict[str, str] = {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Review created tools for security and correctness.

        Args:
            state: Workflow state with 'created_tools' list.

        Returns:
            Updated state with 'review_results' and optionally
            'pending_human_reviews' for tools requiring human review.
        """
        created_tools: list[dict] = state.get("created_tools", [])
        review_results: list[dict] = []
        pending_human: list[dict] = []

        for tool_info in created_tools:
            tool_name = tool_info.get("name", "")

            if self._require_human_review:
                review_path = f"/api/reviews/tools/{tool_name}"
                self._pending_reviews[tool_name] = review_path
                pending_human.append({
                    "tool_name": tool_name,
                    "review_url": review_path,
                    "status": "pending_human_review",
                })
                review_results.append({
                    "tool_name": tool_name,
                    "status": "pending_human_review",
                    "review_url": review_path,
                })
            else:
                passed, issues = self._auto_review(tool_info)
                review_results.append({
                    "tool_name": tool_name,
                    "status": "approved" if passed else "rejected",
                    "issues": issues,
                })

        state["review_results"] = review_results
        if pending_human:
            state["pending_human_reviews"] = pending_human
        return state

    def _auto_review(self, tool_info: dict) -> tuple[bool, list[str]]:
        """Perform automated security review of a tool.

        Args:
            tool_info: Dict with tool name and path.

        Returns:
            A tuple of (passed, issues_list).
        """
        issues: list[str] = []
        tool_name = tool_info.get("name", "")
        tool_path = tool_info.get("path", "")

        if not tool_name.startswith("tool_"):
            issues.append(f"Tool name '{tool_name}' does not follow naming convention (tool_<skill>_<func>)")

        dangerous_patterns = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd", "format c:"]
        try:
            from pathlib import Path
            if tool_path and Path(tool_path).exists():
                content = Path(tool_path).read_text(encoding="utf-8")
                for pattern in dangerous_patterns:
                    if pattern in content:
                        issues.append(f"Dangerous pattern detected: {pattern}")
        except Exception:
            pass

        if self._llm and tool_path:
            llm_issues = self._llm_review(tool_name, tool_path)
            issues.extend(llm_issues)

        return len(issues) == 0, issues

    def _llm_review(self, tool_name: str, tool_path: str) -> list[str]:
        """Use LLM to review tool security.

        Args:
            tool_name: Name of the tool.
            tool_path: Path to the tool file.

        Returns:
            A list of security issues found.
        """
        if self._llm is None:
            return []

        try:
            from pathlib import Path
            content = Path(tool_path).read_text(encoding="utf-8")
        except Exception:
            return ["Could not read tool file for review"]

        prompt = (
            f"Review this tool '{tool_name}' for security issues:\n\n"
            f"{content}\n\n"
            f"List any security concerns. Return a JSON list of issue strings, or [] if none."
        )
        try:
            import json
            response = self._llm.invoke(prompt)
            issues = json.loads(response.content)
            if isinstance(issues, list):
                return [str(i) for i in issues]
        except Exception:
            pass
        return []

    def submit_human_review(self, tool_name: str, approved: bool) -> dict[str, Any]:
        """Submit a human review result for a tool.

        Args:
            tool_name: Name of the tool being reviewed.
            approved: Whether the human approved the tool.

        Returns:
            A dict with the review result.
        """
        if tool_name in self._pending_reviews:
            del self._pending_reviews[tool_name]
        return {
            "tool_name": tool_name,
            "status": "approved" if approved else "rejected",
        }
