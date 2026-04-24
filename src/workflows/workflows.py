from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from src.config.schema import LibrarianConfig
from src.workers.skill_router import SkillRouter
from src.workers.skill_evaluator import SkillEvaluator
from src.workers.skill_deduplicator import SkillDeduplicator
from src.workers.skill_splitter import SkillSplitter
from src.workers.skill_pruner import SkillPruner
from src.workers.skill_link_maintainer import SkillLinkMaintainer
from src.workers.tool_synthesizer import ToolSynthesizer
from src.workers.tool_guardian import ToolGuardian


class Case1Workflow:
    """Workflow for processing new skills arriving at the system.

    Implements the full pipeline:
    Router → (Deduplicator/Splitter) → Evaluator → (ToolSynthesizer → ToolGuardian) → Commit/Rollback

    Attributes:
        config: The Librarian configuration.
        router: SkillRouter instance.
        deduplicator: SkillDeduplicator instance.
        splitter: SkillSplitter instance.
        evaluator: SkillEvaluator instance.
        tool_synthesizer: ToolSynthesizer instance.
        tool_guardian: ToolGuardian instance.
        link_maintainer: SkillLinkMaintainer instance.
    """

    def __init__(self, config: LibrarianConfig) -> None:
        """Initialize the Case1 workflow with lazy-loaded workers.

        Args:
            config: The Librarian configuration for worker initialization.
        """
        self.config = config
        self.router = SkillRouter()
        self.deduplicator = SkillDeduplicator()
        self.splitter = SkillSplitter()
        self.evaluator = SkillEvaluator()
        self.tool_synthesizer = ToolSynthesizer()
        self.tool_guardian = ToolGuardian()
        self.link_maintainer = SkillLinkMaintainer()

    def _ensure_workers_initialized(self, state: dict[str, Any]) -> None:
        """Lazily initialize all workers if not already done.

        Args:
            state: The workflow state (used for context).
        """
        for worker in [
            self.router, self.deduplicator, self.splitter,
            self.evaluator, self.tool_synthesizer, self.tool_guardian,
            self.link_maintainer,
        ]:
            worker.ensure_initialized(self.config)

    def route_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the router to determine actions for each skill.

        Args:
            state: Workflow state with pending_skills.

        Returns:
            Updated state with route_decisions.
        """
        self._ensure_workers_initialized(state)
        state["split_rule"] = {
            "max_lines": self.config.workers.skill_splitter.split_rule.max_lines,
            "min_lines": self.config.workers.skill_splitter.split_rule.min_lines,
        }
        state["max_rejection_count"] = self.config.max_rejection_count
        return self.router.execute(state)

    def deduplicate_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the deduplicator to find merge groups.

        Args:
            state: Workflow state with pending_skills.

        Returns:
            Updated state with merge_groups.
        """
        self._ensure_workers_initialized(state)
        return self.deduplicator.execute(state)

    def split_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the splitter for skills marked for splitting.

        Args:
            state: Workflow state with route_decisions.

        Returns:
            Updated state with split_results.
        """
        self._ensure_workers_initialized(state)
        return self.splitter.execute(state)

    def evaluate_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the evaluator to score and classify skills.

        Args:
            state: Workflow state with pending_skills.

        Returns:
            Updated state with evaluation_results, missing_tools, etc.
        """
        self._ensure_workers_initialized(state)
        return self.evaluator.execute(state)

    def synthesize_tools_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool synthesizer for missing tools.

        Args:
            state: Workflow state with missing_tools.

        Returns:
            Updated state with created_tools.
        """
        self._ensure_workers_initialized(state)
        return self.tool_synthesizer.execute(state)

    def review_tools_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool guardian to review created tools.

        Args:
            state: Workflow state with created_tools.

        Returns:
            Updated state with review_results.
        """
        self._ensure_workers_initialized(state)
        return self.tool_guardian.execute(state)

    def commit_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Commit approved changes to the git repository.

        Moves files from tmp directories to formal locations and commits.

        Args:
            state: Workflow state with evaluation_results.

        Returns:
            Updated state with commit_status.
        """
        from src.db.manager import DatabaseManager
        from src.git_manager.manager import GitManager
        from src.git_manager.tmp_manager import TmpManager
        from src.tools.builtin import UpdateSkillFrontmatterTool

        db: DatabaseManager | None = state.get("db")
        git_mgr: GitManager | None = state.get("git_manager")
        tmp_mgr: TmpManager | None = state.get("tmp_manager")
        skills_dir = state.get("skills_dir")

        evaluation_results: list[dict] = state.get("evaluation_results", [])
        committed: list[str] = []
        rejected: list[str] = state.get("rejected_skills", [])

        for result in evaluation_results:
            skill_name = result.get("skill_name", "")
            if result.get("passed", False) and skill_name not in rejected:
                if db:
                    update_tool = UpdateSkillFrontmatterTool(
                        db, __import__("pathlib").Path(skills_dir) if skills_dir else None
                    )
                    try:
                        update_tool.run(
                            skill_name,
                            confidence_score=result.get("confidence_score", 0.0),
                            categories=result.get("categories", []),
                        )
                    except Exception:
                        pass
                committed.append(skill_name)

        if git_mgr and git_mgr.has_changes():
            git_mgr.add()
            git_mgr.commit(f"Librarian: processed {len(committed)} skills")

        state["commit_status"] = {
            "committed": committed,
            "rejected": rejected,
        }
        return state

    def rollback_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Rollback changes for rejected skills.

        Args:
            state: Workflow state with rejected_skills.

        Returns:
            Updated state with rollback_status.
        """
        from src.git_manager.tmp_manager import TmpManager

        tmp_mgr: TmpManager | None = state.get("tmp_manager")
        job_id = state.get("job_id")

        if tmp_mgr and job_id:
            tmp_mgr.cleanup_tmp(job_id)

        state["rollback_status"] = {
            "rolled_back": state.get("rejected_skills", []),
        }
        return state

    def should_deduplicate(self, state: dict[str, Any]) -> str:
        """Determine if deduplication is needed based on route decisions.

        Args:
            state: Workflow state with route_decisions.

        Returns:
            'deduplicate' if any skill needs merging, else 'check_split'.
        """
        decisions = state.get("route_decisions", {})
        if any(v == "merge" for v in decisions.values()):
            return "deduplicate"
        return "check_split"

    def should_split(self, state: dict[str, Any]) -> str:
        """Determine if splitting is needed based on route decisions.

        Args:
            state: Workflow state with route_decisions.

        Returns:
            'split' if any skill needs splitting, else 'evaluate'.
        """
        decisions = state.get("route_decisions", {})
        if any(v == "split" for v in decisions.values()):
            return "split"
        return "evaluate"

    def should_create_tools(self, state: dict[str, Any]) -> str:
        """Determine if tool creation is needed.

        Args:
            state: Workflow state with missing_tools.

        Returns:
            'create_tools' if there are missing tools, else 'commit'.
        """
        if state.get("missing_tools"):
            return "create_tools"
        return "commit"

    def should_commit_or_rollback(self, state: dict[str, Any]) -> str:
        """Determine if changes should be committed or rolled back.

        Args:
            state: Workflow state with evaluation_results and rejected_skills.

        Returns:
            'commit' if any skills passed, else 'rollback'.
        """
        results = state.get("evaluation_results", [])
        if any(r.get("passed", False) for r in results):
            return "commit"
        return "rollback"

    def build_graph(self) -> StateGraph:
        """Build the LangGraph state graph for Case 1 workflow.

        Returns:
            A compiled StateGraph ready for execution.
        """
        graph = StateGraph(dict[str, Any])

        graph.add_node("route", self.route_node)
        graph.add_node("deduplicate", self.deduplicate_node)
        graph.add_node("split", self.split_node)
        graph.add_node("evaluate", self.evaluate_node)
        graph.add_node("create_tools", self.synthesize_tools_node)
        graph.add_node("review_tools", self.review_tools_node)
        graph.add_node("commit", self.commit_node)
        graph.add_node("rollback", self.rollback_node)

        graph.set_entry_point("route")

        graph.add_conditional_edges("route", self.should_deduplicate, {
            "deduplicate": "deduplicate",
            "check_split": "split",
        })
        graph.add_edge("deduplicate", "split")
        graph.add_conditional_edges("split", self.should_split, {
            "split": "split",
            "evaluate": "evaluate",
        })
        graph.add_edge("evaluate", "create_tools")
        graph.add_conditional_edges("create_tools", self.should_create_tools, {
            "create_tools": "review_tools",
            "commit": "commit",
        })
        graph.add_edge("review_tools", "commit")
        graph.add_conditional_edges("commit", self.should_commit_or_rollback, {
            "commit": END,
            "rollback": "rollback",
        })
        graph.add_edge("rollback", END)

        return graph.compile()


class Case2Workflow:
    """Workflow for periodic merge checks.

    Deduplicator → LinkMaintainer

    Attributes:
        config: The Librarian configuration.
        deduplicator: SkillDeduplicator instance.
        link_maintainer: SkillLinkMaintainer instance.
    """

    def __init__(self, config: LibrarianConfig) -> None:
        """Initialize the Case2 workflow.

        Args:
            config: The Librarian configuration.
        """
        self.config = config
        self.deduplicator = SkillDeduplicator()
        self.link_maintainer = SkillLinkMaintainer()

    def deduplicate_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run deduplication on all existing skills.

        Args:
            state: Workflow state with db and skills_dir.

        Returns:
            Updated state with merge_groups.
        """
        self.deduplicator.ensure_initialized(self.config)
        from src.db.manager import DatabaseManager
        from src.models.file_io import read_skill_file

        db: DatabaseManager | None = state.get("db")
        skills_dir = state.get("skills_dir")
        if db and skills_dir:
            all_skills = db.get_all_skills()
            pending: list[dict] = []
            for s in all_skills:
                from pathlib import Path
                path = Path(skills_dir) / f"{s['skill_name']}.md"
                if path.exists():
                    skill = read_skill_file(path)
                    pending.append({"name": s["skill_name"], "content": skill.content})
            state["pending_skills"] = pending

        return self.deduplicator.execute(state)

    def maintain_links_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Update links after merge operations.

        Args:
            state: Workflow state with merge_groups.

        Returns:
            Updated state with link_updates.
        """
        self.link_maintainer.ensure_initialized(self.config)
        return self.link_maintainer.execute(state)

    def build_graph(self) -> StateGraph:
        """Build the LangGraph state graph for Case 2 workflow.

        Returns:
            A compiled StateGraph ready for execution.
        """
        graph = StateGraph(dict[str, Any])
        graph.add_node("deduplicate", self.deduplicate_node)
        graph.add_node("maintain_links", self.maintain_links_node)
        graph.set_entry_point("deduplicate")
        graph.add_edge("deduplicate", "maintain_links")
        graph.add_edge("maintain_links", END)
        return graph.compile()


class Case3Workflow:
    """Workflow for periodic cleanup checks.

    Pruner → LinkMaintainer

    Attributes:
        config: The Librarian configuration.
        pruner: SkillPruner instance.
        link_maintainer: SkillLinkMaintainer instance.
    """

    def __init__(self, config: LibrarianConfig) -> None:
        """Initialize the Case3 workflow.

        Args:
            config: The Librarian configuration.
        """
        self.config = config
        self.pruner = SkillPruner()
        self.link_maintainer = SkillLinkMaintainer()

    def prune_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run cleanup on expired skills.

        Args:
            state: Workflow state with db.

        Returns:
            Updated state with expired_skills.
        """
        self.pruner.ensure_initialized(self.config)
        return self.pruner.execute(state)

    def maintain_links_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Update links after cleanup operations.

        Args:
            state: Workflow state with expired_skills.

        Returns:
            Updated state with link_updates.
        """
        self.link_maintainer.ensure_initialized(self.config)
        state["removed_skills"] = state.get("expired_skills", [])
        return self.link_maintainer.execute(state)

    def build_graph(self) -> StateGraph:
        """Build the LangGraph state graph for Case 3 workflow.

        Returns:
            A compiled StateGraph ready for execution.
        """
        graph = StateGraph(dict[str, Any])
        graph.add_node("prune", self.prune_node)
        graph.add_node("maintain_links", self.maintain_links_node)
        graph.set_entry_point("prune")
        graph.add_edge("prune", "maintain_links")
        graph.add_edge("maintain_links", END)
        return graph.compile()
