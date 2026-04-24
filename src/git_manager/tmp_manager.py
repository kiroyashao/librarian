from __future__ import annotations

import shutil
from pathlib import Path


class TmpManager:
    """Manages temporary directories for job-based file staging within a repository.

    Creates, moves, and cleans up temporary directories under .tmp/ in the
    repository root. Each job gets its own isolated subdirectory.

    Args:
        repo_path: The root directory of the repository where .tmp/ lives.

    Attributes:
        repo_path: The resolved absolute path to the repository root.
        tmp_root: The path to the .tmp/ directory under repo_path.
    """

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()
        self.tmp_root = self.repo_path / ".tmp"

    def create_tmp_dir(self, job_id: str) -> Path:
        """Create a temporary directory for the given job.

        Args:
            job_id: Unique identifier for the job.

        Returns:
            The Path to the created temporary directory (.tmp/<job_id>/).

        Raises:
            FileExistsError: If a tmp directory for this job_id already exists.
        """
        tmp_dir = self.tmp_root / job_id
        tmp_dir.mkdir(parents=True, exist_ok=False)
        return tmp_dir

    def move_to_formal(self, job_id: str, target_dir: Path) -> None:
        """Move all files from the job's tmp directory to a target directory.

        After moving all files, the tmp directory for the job is removed.

        Args:
            job_id: Unique identifier for the job whose tmp dir to move.
            target_dir: The destination directory to move files into.

        Raises:
            FileNotFoundError: If the tmp directory for the job does not exist.
        """
        tmp_dir = self.get_tmp_dir(job_id)
        if not tmp_dir.exists():
            raise FileNotFoundError(f"Tmp directory not found: {tmp_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in tmp_dir.iterdir():
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dest))
        shutil.rmtree(str(tmp_dir))

    def cleanup_tmp(self, job_id: str) -> None:
        """Remove the tmp directory and all its contents for the given job.

        Args:
            job_id: Unique identifier for the job whose tmp dir to remove.

        Raises:
            FileNotFoundError: If the tmp directory for the job does not exist.
        """
        tmp_dir = self.get_tmp_dir(job_id)
        if not tmp_dir.exists():
            raise FileNotFoundError(f"Tmp directory not found: {tmp_dir}")
        shutil.rmtree(str(tmp_dir))

    def list_tmp_dirs(self) -> list[str]:
        """List all job IDs that have existing tmp directories.

        Returns:
            A list of job_id strings for which .tmp/<job_id>/ directories exist.
        """
        if not self.tmp_root.exists():
            return []
        return [d.name for d in self.tmp_root.iterdir() if d.is_dir()]

    def get_tmp_dir(self, job_id: str) -> Path:
        """Get the Path for a specific job's tmp directory.

        This method does not check whether the directory exists; it simply
        returns the expected path.

        Args:
            job_id: Unique identifier for the job.

        Returns:
            The Path to .tmp/<job_id>/ under the repository root.
        """
        return self.tmp_root / job_id
