from __future__ import annotations


class GitError(Exception):
    """Custom exception for git operation failures.

    Raised when a git command executed via subprocess returns a non-zero
    exit code or when a git operation cannot be performed.

    Attributes:
        message: Human-readable description of the failure.
        stderr: The stderr output from the git command, if available.
    """

    def __init__(self, message: str, stderr: str | None = None) -> None:
        self.message = message
        self.stderr = stderr
        detail = f"{message}" + (f": {stderr}" if stderr else "")
        super().__init__(detail)
