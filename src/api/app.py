from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.config.loader import ConfigLoader
from src.config.schema import LibrarianConfig
from src.db.manager import DatabaseManager
from src.git_manager.manager import GitManager
from src.git_manager.tmp_manager import TmpManager
from src.models.file_io import list_skill_files, read_skill_file
from src.models.skill import SkillFile, SkillFrontmatter
from src.tools.builtin import (
    CheckSkillLinksTool,
    GetSkillLinksTool,
    PushSkillsTool,
    RemoveSkillsTool,
    UpdateSkillFrontmatterTool,
)
from src.workflows.human_review import HumanReviewManager
from src.workflows.workflows import Case1Workflow

logger = logging.getLogger(__name__)


class SkillSubmitRequest(BaseModel):
    """Request body for submitting a new skill."""
    name: str
    content: str
    description: str = ""
    author: str = ""
    link_path: str | None = None


class ReviewSubmitRequest(BaseModel):
    """Request body for submitting a human review."""
    approved: bool
    comment: str = ""


def create_app(
    config: LibrarianConfig,
    config_loader: ConfigLoader,
    db: DatabaseManager,
    git_manager: GitManager,
    tmp_manager: TmpManager,
    human_review_manager: HumanReviewManager,
    skills_dir: Path,
    tools_dir: Path,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: The Librarian configuration.
        config_loader: The config loader for hot-reload.
        db: The database manager.
        git_manager: The git version control manager.
        tmp_manager: The temporary directory manager.
        human_review_manager: The human review manager.
        skills_dir: Path to the skills directory.
        tools_dir: Path to the tools directory.

    Returns:
        A configured FastAPI application.
    """
    app = FastAPI(title="Librarian Skills Manager", version="0.1.0")

    _pending_skills: list[dict[str, Any]] = []

    @app.get("/skills")
    def get_skills() -> list[dict[str, Any]]:
        """Get all skills."""
        return db.get_all_skills()

    @app.post("/skills")
    def submit_skill(request: SkillSubmitRequest) -> dict[str, Any]:
        """Submit a new skill to the system."""
        push_tool = PushSkillsTool(db, skills_dir)
        result = push_tool.run(
            skill_name=request.name,
            content=request.content,
            description=request.description,
            author=request.author,
            link_path=request.link_path,
        )

        _pending_skills.append({
            "name": request.name,
            "content": request.content,
        })

        if len(_pending_skills) >= config.skill_trigger_threshold:
            _trigger_case1()

        return result

    @app.get("/skills/search")
    def search_skills(q: str = Query(..., description="Search query")) -> list[dict[str, Any]]:
        """Search skills by name."""
        return db.search_skills(q)

    @app.get("/skills/{skill_name}")
    def get_skill(skill_name: str) -> dict[str, Any]:
        """Get a single skill by name."""
        skill_record = db.get_skill(skill_name)
        if skill_record is None:
            raise HTTPException(status_code=404, detail="Skill not found")

        path = skills_dir / f"{skill_name}.md"
        if path.exists():
            skill_file = read_skill_file(path)
            return {
                "record": skill_record,
                "frontmatter": skill_file.frontmatter.model_dump(mode="json"),
                "content": skill_file.content,
            }
        return {"record": skill_record}

    @app.delete("/skills/{skill_name}")
    def delete_skill(skill_name: str) -> dict[str, Any]:
        """Delete a skill and its associated data."""
        remove_tool = RemoveSkillsTool(db, skills_dir, tools_dir)
        result = remove_tool.run([skill_name])
        return result

    @app.get("/skills/{skill_name}/links")
    def get_skill_links(skill_name: str) -> dict[str, Any]:
        """Get link relationships for a skill."""
        tool = GetSkillLinksTool(db)
        return tool.run(skill_name)

    @app.get("/git/history")
    def get_git_history(count: int = 20) -> list[dict[str, Any]]:
        """View git change history."""
        return git_manager.log(count=count)

    @app.post("/git/rollback/{commit_id}")
    def rollback_git(commit_id: str) -> dict[str, Any]:
        """Rollback to a specific commit."""
        try:
            git_manager.rollback(commit_id)
            return {"status": "rolled_back", "commit_id": commit_id}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        """Get current configuration."""
        return config.model_dump(mode="json")

    @app.get("/tools")
    def get_tools() -> list[dict[str, Any]]:
        """Get all tools with reference counts."""
        return db.get_all_tools_refs()

    @app.get("/reviews")
    def get_pending_reviews() -> list[dict[str, Any]]:
        """Get all pending human reviews."""
        return human_review_manager.get_pending_reviews()

    @app.post("/reviews/{review_id}")
    def submit_review(review_id: str, request: ReviewSubmitRequest) -> dict[str, Any]:
        """Submit a human review result."""
        result = human_review_manager.submit_review(
            review_id, request.approved, request.comment
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Review not found")
        return result

    def _trigger_case1() -> None:
        """Trigger the Case1 workflow when threshold is reached."""
        try:
            workflow = Case1Workflow(config)
            graph = workflow.build_graph()
            state = {
                "pending_skills": _pending_skills.copy(),
                "db": db,
                "skills_dir": str(skills_dir),
                "tools_dir": str(tools_dir),
                "git_manager": git_manager,
                "tmp_manager": tmp_manager,
            }
            graph.invoke(state)
            _pending_skills.clear()
            logger.info("Case1 workflow triggered and completed")
        except Exception:
            logger.exception("Case1 workflow failed")

    return app
