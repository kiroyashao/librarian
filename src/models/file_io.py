from __future__ import annotations

from pathlib import Path

from src.models.skill import SkillFile


def read_skill_file(path: Path) -> SkillFile:
    """Read a skill file from disk and parse it.

    Args:
        path: Path to the .md skill file.

    Returns:
        A SkillFile instance parsed from the file contents.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    text = path.read_text(encoding="utf-8")
    return SkillFile.from_markdown(text)


def write_skill_file(path: Path, skill: SkillFile) -> None:
    """Write a skill file to disk.

    Creates parent directories if they do not exist.

    Args:
        path: Destination path for the .md skill file.
        skill: The SkillFile to serialize and write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skill.to_markdown(), encoding="utf-8")


def list_skill_files(directory: Path) -> list[Path]:
    """List all .md skill files in a directory.

    Args:
        directory: Directory to search for skill files.

    Returns:
        A sorted list of Paths to .md files.
    """
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))


def delete_skill_file(path: Path) -> None:
    """Delete a skill file from disk.

    Args:
        path: Path to the .md skill file to delete.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path.unlink()
