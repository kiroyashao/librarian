from __future__ import annotations

import subprocess
from pathlib import Path

from src.git_manager.exceptions import GitError


class GitManager:
    """Wraps git commands via subprocess to manage a git repository.

    Provides methods for initializing repos, staging/committing files,
    viewing history, rolling back commits, and checking working tree status.

    Args:
        repo_path: The root directory of the git repository.

    Attributes:
        repo_path: The resolved absolute path to the repository root.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Execute a git command via subprocess.

        Args:
            args: Git command arguments, e.g. ["add", "."].

        Returns:
            The CompletedProcess result from subprocess.run.

        Raises:
            GitError: If the git command returns a non-zero exit code.
        """
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitError(
                message=f"git {' '.join(args)} failed with exit code {result.returncode}",
                stderr=result.stderr.strip(),
            )
        return result

    def init(self) -> None:
        """Initialize a git repository if one does not already exist.

        Creates the repo_path directory if it does not exist, then initializes
        a git repository. Configures user.email as "librarian@local" and
        user.name as "Librarian" in the local repository config.

        Raises:
            GitError: If git init or git config commands fail.
        """
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if not self.is_repo():
            self._run(["init"])
        self._run(["config", "user.email", "librarian@local"])
        self._run(["config", "user.name", "Librarian"])

    def is_repo(self) -> bool:
        """Check if the current path is inside a git repository.

        Returns:
            True if the path is a git repository, False otherwise.
        """
        if not self.repo_path.exists():
            return False
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def add(self, paths: list[str] | None = None) -> None:
        """Stage files for the next commit.

        Args:
            paths: List of file paths to stage. If None, stages all changes.

        Raises:
            GitError: If the git add command fails.
        """
        if paths is None:
            self._run(["add", "-A"])
        else:
            self._run(["add", *paths])

    def commit(self, message: str) -> str:
        """Commit staged changes and return the commit hash.

        Args:
            message: The commit message.

        Returns:
            The full SHA-1 hash of the new commit.

        Raises:
            GitError: If the git commit command fails.
        """
        self._run(["commit", "-m", message])
        result = self._run(["rev-parse", "HEAD"])
        return result.stdout.strip()

    def log(self, count: int = 20) -> list[dict[str, str]]:
        """Get commit history from the repository.

        Args:
            count: Maximum number of commits to retrieve.

        Returns:
            A list of dicts, each containing keys: hash, author, date, message.
            Ordered from most recent to oldest.

        Raises:
            GitError: If the git log command fails.
        """
        format_str = "%H%x00%an%x00%ai%x00%s"
        result = self._run(["log", f"-{count}", f"--format={format_str}"])
        entries: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("\x00")
            if len(parts) >= 4:
                entries.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })
        return entries

    def rollback(self, commit_id: str) -> None:
        """Hard reset the repository to the specified commit.

        Args:
            commit_id: The SHA-1 hash of the commit to reset to.

        Raises:
            GitError: If the git reset command fails.
        """
        self._run(["reset", "--hard", commit_id])

    def get_current_hash(self) -> str:
        """Get the current HEAD commit hash.

        Returns:
            The full SHA-1 hash of the current HEAD commit.

        Raises:
            GitError: If the git rev-parse command fails.
        """
        result = self._run(["rev-parse", "HEAD"])
        return result.stdout.strip()

    def has_changes(self) -> bool:
        """Check if there are uncommitted changes in the working tree.

        Returns:
            True if there are staged or unstaged changes, False otherwise.
        """
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())

    def status(self) -> list[dict[str, str]]:
        """Get the status of files in the working tree.

        Returns:
            A list of dicts, each containing keys: path, status.
            Status values are one of: added, modified, deleted, untracked.
        """
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        entries: list[dict[str, str]] = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            xy = line[:2]
            filepath = line[3:]
            status = self._parse_status(xy)
            entries.append({"path": filepath, "status": status})
        return entries

    @staticmethod
    def _parse_status(xy: str) -> str:
        """Map git porcelain status codes to human-readable status strings.

        Args:
            xy: The two-character status code from git status --porcelain.

        Returns:
            One of: "added", "modified", "deleted", "untracked".
        """
        if xy[0] == "?" or xy[1] == "?":
            return "untracked"
        if xy[0] == "A" or xy[1] == "A":
            return "added"
        if xy[0] == "D" or xy[1] == "D":
            return "deleted"
        return "modified"
