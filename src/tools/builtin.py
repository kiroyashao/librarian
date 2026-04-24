from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.db.manager import DatabaseManager
from src.models.skill import SkillFile, SkillFrontmatter, SkillMetadata
from src.models.file_io import read_skill_file, write_skill_file, list_skill_files, delete_skill_file


class UpdateSkillFrontmatterTool:
    """Updates a skill's YAML frontmatter fields and syncs the database.

    Attributes:
        db: The database manager for persisting changes.
        skills_dir: Directory where skill files are stored.
    """

    def __init__(self, db: DatabaseManager, skills_dir: Path) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
            skills_dir: Path to the directory containing skill .md files.
        """
        self.db = db
        self.skills_dir = skills_dir

    def run(
        self,
        skill_name: str,
        confidence_score: float | None = None,
        categories: list[str] | None = None,
        **extra_fields: Any,
    ) -> dict[str, Any]:
        """Update frontmatter fields for a skill.

        Args:
            skill_name: Name of the skill to update.
            confidence_score: New confidence score, or None to keep current.
            categories: New categories list, or None to keep current.
            **extra_fields: Additional frontmatter fields to update.

        Returns:
            A dict with 'status' and updated 'frontmatter' keys.

        Raises:
            FileNotFoundError: If the skill file does not exist.
        """
        path = self.skills_dir / f"{skill_name}.md"
        skill = read_skill_file(path)

        if confidence_score is not None:
            skill.frontmatter.metadata.confidence_score = confidence_score
        if categories is not None:
            skill.frontmatter.metadata.categories = categories
        skill.frontmatter.metadata.update_times += 1
        skill.frontmatter.metadata.last_update_at = datetime.now(timezone.utc)

        for key, value in extra_fields.items():
            if hasattr(skill.frontmatter, key):
                setattr(skill.frontmatter, key, value)

        write_skill_file(path, skill)
        self.db.update_skill_timestamps(
            skill_name, last_update_at=datetime.now(timezone.utc)
        )

        return {
            "status": "updated",
            "frontmatter": skill.frontmatter.model_dump(mode="json"),
        }


class CheckSkillLinksTool:
    """Validates skill references and updates the skills_links table.

    Checks that all ``[[skills: ...]]`` and ``[[tools: ...]]`` references
    in a skill's content point to existing files or tools.

    Attributes:
        db: The database manager for link persistence.
        skills_dir: Directory where skill files are stored.
        tools_dir: Directory where tool files are stored.
    """

    def __init__(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
            skills_dir: Path to the skills directory.
            tools_dir: Path to the tools directory.
        """
        self.db = db
        self.skills_dir = skills_dir
        self.tools_dir = tools_dir

    def run(self, skill_name: str) -> dict[str, Any]:
        """Check and update links for a skill.

        Args:
            skill_name: Name of the skill to check.

        Returns:
            A dict with 'valid', 'broken', and 'updated' keys.
        """
        path = self.skills_dir / f"{skill_name}.md"
        if not path.exists():
            return {"valid": [], "broken": [], "updated": False, "error": "skill not found"}

        skill = read_skill_file(path)
        refs = skill.extract_references()

        valid: list[str] = []
        broken: list[str] = []

        for ref in refs:
            if ref.ref_type == "skills":
                target = self.skills_dir / f"{ref.name}.md"
                if target.exists():
                    valid.append(f"skills:{ref.name}")
                else:
                    broken.append(f"skills:{ref.name}")
            elif ref.ref_type == "tools":
                target = self.tools_dir / f"{ref.name}"
                if target.exists():
                    valid.append(f"tools:{ref.name}")
                else:
                    broken.append(f"tools:{ref.name}")
            elif ref.ref_type == "references":
                valid.append(f"references:{ref.name}")

        self.db.delete_skill_links(skill_name)
        for item in valid:
            self.db.add_skill_link(skill_name, item)

        return {"valid": valid, "broken": broken, "updated": True}


class MergeSkillsTool:
    """Merges duplicate or similar skills into one.

    Attributes:
        db: The database manager for persisting changes.
        skills_dir: Directory where skill files are stored.
        tools_dir: Directory where tool files are stored.
    """

    def __init__(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
            skills_dir: Path to the skills directory.
            tools_dir: Path to the tools directory.
        """
        self.db = db
        self.skills_dir = skills_dir
        self.tools_dir = tools_dir

    def run(
        self,
        target_name: str,
        source_names: list[str],
        merged_content: str,
        merged_frontmatter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge multiple skills into a single target skill.

        Args:
            target_name: Name for the merged skill.
            source_names: Names of the skills being merged.
            merged_content: The combined markdown content.
            merged_frontmatter: Optional frontmatter overrides for the merged skill.

        Returns:
            A dict with 'status', 'target', and 'sources_removed' keys.
        """
        fm_data = merged_frontmatter or {"name": target_name}
        fm_data["name"] = target_name
        frontmatter = SkillFrontmatter.model_validate(fm_data)
        merged = SkillFile(frontmatter=frontmatter, content=merged_content)

        target_path = self.skills_dir / f"{target_name}.md"
        write_skill_file(target_path, merged)
        self.db.upsert_skill(target_name)

        all_tool_refs: set[str] = set()
        for source_name in source_names:
            source_path = self.skills_dir / f"{source_name}.md"
            if source_path.exists():
                source_skill = read_skill_file(source_path)
                for ref in source_skill.extract_references():
                    if ref.ref_type == "tools":
                        all_tool_refs.add(ref.name)
                delete_skill_file(source_path)
            self.db.delete_skill(source_name)

        for tool_name in all_tool_refs:
            self.db.increment_tool_ref(tool_name)

        return {
            "status": "merged",
            "target": target_name,
            "sources_removed": source_names,
        }


class RemoveSkillsTool:
    """Removes invalid skills and cleans up related database records.

    Decrements tool reference counts and deletes tools whose count drops to 0.

    Attributes:
        db: The database manager for persisting changes.
        skills_dir: Directory where skill files are stored.
        tools_dir: Directory where tool files are stored.
    """

    def __init__(self, db: DatabaseManager, skills_dir: Path, tools_dir: Path) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
            skills_dir: Path to the skills directory.
            tools_dir: Path to the tools directory.
        """
        self.db = db
        self.skills_dir = skills_dir
        self.tools_dir = tools_dir

    def run(self, skill_names: list[str]) -> dict[str, Any]:
        """Remove skills and clean up references.

        Args:
            skill_names: Names of the skills to remove.

        Returns:
            A dict with 'removed_skills' and 'removed_tools' keys.
        """
        removed_skills: list[str] = []
        removed_tools: list[str] = []

        for skill_name in skill_names:
            path = self.skills_dir / f"{skill_name}.md"
            tool_refs: list[str] = []

            if path.exists():
                skill = read_skill_file(path)
                tool_refs = [
                    ref.name for ref in skill.extract_references() if ref.ref_type == "tools"
                ]
                delete_skill_file(path)

            self.db.delete_skill(skill_name)
            removed_skills.append(skill_name)

            for tool_name in tool_refs:
                new_count = self.db.decrement_tool_ref(tool_name)
                if new_count == 0:
                    tool_path = self.tools_dir / tool_name
                    if tool_path.exists():
                        tool_path.unlink()
                    removed_tools.append(tool_name)

        return {
            "removed_skills": removed_skills,
            "removed_tools": removed_tools,
        }


class GetSkillLinksTool:
    """Retrieves link relationships for a skill from the database.

    Attributes:
        db: The database manager for reading link data.
    """

    def __init__(self, db: DatabaseManager) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
        """
        self.db = db

    def run(self, skill_name: str) -> dict[str, Any]:
        """Get all links for a skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            A dict with 'skill_name' and 'links' keys.
        """
        links = self.db.get_skill_links(skill_name)
        return {"skill_name": skill_name, "links": links}


class PushSkillsTool:
    """Submits skill content to the librarian system.

    Writes the skill file and updates the database.

    Attributes:
        db: The database manager for persisting changes.
        skills_dir: Directory where skill files are stored.
    """

    def __init__(self, db: DatabaseManager, skills_dir: Path) -> None:
        """Initialize the tool.

        Args:
            db: DatabaseManager instance for database operations.
            skills_dir: Path to the skills directory.
        """
        self.db = db
        self.skills_dir = skills_dir

    def run(
        self,
        skill_name: str,
        content: str,
        description: str = "",
        author: str = "",
        link_path: str | None = None,
    ) -> dict[str, Any]:
        """Submit a new or updated skill.

        Args:
            skill_name: Name of the skill.
            content: Markdown body of the skill.
            description: Description for the frontmatter.
            author: Author name for the frontmatter.
            link_path: Optional link path to associate.

        Returns:
            A dict with 'status' and 'skill_name' keys.
        """
        path = self.skills_dir / f"{skill_name}.md"

        if path.exists():
            skill = read_skill_file(path)
            skill.content = content
            if description:
                skill.frontmatter.description = description
        else:
            frontmatter = SkillFrontmatter(
                name=skill_name,
                description=description,
                author=author,
            )
            skill = SkillFile(frontmatter=frontmatter, content=content)

        write_skill_file(path, skill)
        self.db.upsert_skill(skill_name)

        if link_path:
            self.db.add_skill_link(skill_name, link_path)

        return {"status": "pushed", "skill_name": skill_name}
