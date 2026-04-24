from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Metadata for a skill, including timestamps and quality metrics.

    Attributes:
        create_at: When the skill was created.
        last_update_at: When the skill was last updated.
        update_times: Number of times the skill has been updated.
        confidence_score: Quality score between 0.0 and 1.0.
        categories: List of category tags for the skill.
    """

    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_update_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    update_times: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    categories: list[str] = Field(default_factory=list)


class SkillFrontmatter(BaseModel):
    """YAML frontmatter for a skill file.

    Attributes:
        name: Unique name of the skill.
        description: Human-readable description.
        author: Name of the agent that created the skill.
        version: Semantic version string.
        os: List of supported operating systems.
        dependencies: Mapping of dependency types to version specifiers.
        metadata: Additional metadata including timestamps and scores.
    """

    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    os: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    metadata: SkillMetadata = Field(default_factory=SkillMetadata)


class SkillReference(BaseModel):
    """A parsed reference from skill content.

    Attributes:
        ref_type: Type of reference — one of 'skills', 'tools', or 'references'.
        name: Name of the referenced item.
    """

    ref_type: str
    name: str


_REF_PATTERN = re.compile(r"\[\[(skills|tools|references):\s*(\S+?)\]\]")


class SkillFile(BaseModel):
    """A complete skill file with frontmatter and markdown content.

    Attributes:
        frontmatter: The parsed YAML frontmatter.
        content: The markdown body after the frontmatter delimiter.
    """

    frontmatter: SkillFrontmatter
    content: str = ""

    def extract_references(self) -> list[SkillReference]:
        """Parse the content for skill, tool, and reference links.

        Finds all occurrences of ``[[skills: name]]``,
        ``[[tools: name]]``, and ``[[references: name]]`` in the
        markdown body.

        Returns:
            A list of SkillReference objects in order of appearance.
        """
        refs: list[SkillReference] = []
        for match in _REF_PATTERN.finditer(self.content):
            refs.append(
                SkillReference(ref_type=match.group(1), name=match.group(2))
            )
        return refs

    def to_markdown(self) -> str:
        """Serialize the skill to a markdown string with YAML frontmatter.

        Returns:
            A string with ``---``-delimited YAML frontmatter followed by
            the markdown content.
        """
        fm_dict = self.frontmatter.model_dump(mode="json")
        fm_yaml = yaml.dump(
            fm_dict, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
        return f"---\n{fm_yaml}---\n{self.content}"

    @classmethod
    def from_markdown(cls, text: str) -> SkillFile:
        """Parse a markdown string with YAML frontmatter into a SkillFile.

        Expects the text to start with ``---``, followed by YAML, then
        another ``---``, and the markdown body.

        Args:
            text: The full markdown text including frontmatter.

        Returns:
            A SkillFile instance with parsed frontmatter and content.

        Raises:
            ValueError: If the frontmatter delimiters are not found.
        """
        if not text.startswith("---"):
            raise ValueError("Skill file must start with '---' frontmatter delimiter")

        end_match = re.search(r"\n---\s*\n", text[3:])
        if end_match is None:
            raise ValueError("Could not find closing '---' frontmatter delimiter")

        fm_text = text[3 : 3 + end_match.start()]
        content = text[3 + end_match.end() :]

        fm_data: dict[str, Any] = yaml.safe_load(fm_text) or {}
        frontmatter = SkillFrontmatter.model_validate(fm_data)
        return cls(frontmatter=frontmatter, content=content)
