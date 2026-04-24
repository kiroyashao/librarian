from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.git_manager.exceptions import GitError
from src.git_manager.manager import GitManager
from src.git_manager.tmp_manager import TmpManager


@pytest.fixture()
def repo_dir(tmp_path: Path) -> Path:
    return tmp_path / "repo"


@pytest.fixture()
def git(repo_dir: Path) -> GitManager:
    gm = GitManager(repo_dir)
    gm.init()
    return gm


@pytest.fixture()
def tmp_mgr(repo_dir: Path) -> TmpManager:
    return TmpManager(repo_dir)


class TestGitManagerInit:
    """Tests for GitManager.init and is_repo."""

    def test_init_creates_repo(self, repo_dir: Path) -> None:
        gm = GitManager(repo_dir)
        assert not repo_dir.exists()
        gm.init()
        assert gm.is_repo()

    def test_init_sets_config(self, repo_dir: Path) -> None:
        gm = GitManager(repo_dir)
        gm.init()
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.stdout.strip() == "librarian@local"
        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.stdout.strip() == "Librarian"

    def test_is_repo_false_before_init(self, repo_dir: Path) -> None:
        gm = GitManager(repo_dir)
        assert gm.is_repo() is False

    def test_init_idempotent(self, repo_dir: Path) -> None:
        gm = GitManager(repo_dir)
        gm.init()
        gm.init()
        assert gm.is_repo()


class TestGitManagerAddCommit:
    """Tests for GitManager.add and commit."""

    def test_add_all_and_commit(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "file.txt").write_text("hello", encoding="utf-8")
        git.add()
        commit_hash = git.commit("initial commit")
        assert isinstance(commit_hash, str)
        assert len(commit_hash) == 40

    def test_add_specific_paths(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "a.txt").write_text("a", encoding="utf-8")
        (repo_dir / "b.txt").write_text("b", encoding="utf-8")
        git.add(paths=["a.txt"])
        commit_hash = git.commit("add a only")
        assert len(commit_hash) == 40

    def test_commit_returns_hash(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("content", encoding="utf-8")
        git.add()
        h = git.commit("msg")
        assert h == git.get_current_hash()

    def test_commit_nothing_staged_raises(self, git: GitManager) -> None:
        with pytest.raises(GitError):
            git.commit("empty commit")


class TestGitManagerLog:
    """Tests for GitManager.log."""

    def test_log_returns_commits(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f1.txt").write_text("1", encoding="utf-8")
        git.add()
        git.commit("first")
        (repo_dir / "f2.txt").write_text("2", encoding="utf-8")
        git.add()
        git.commit("second")
        entries = git.log()
        assert len(entries) == 2
        assert entries[0]["message"] == "second"
        assert entries[1]["message"] == "first"
        assert "hash" in entries[0]
        assert "author" in entries[0]
        assert "date" in entries[0]

    def test_log_respects_count(self, git: GitManager, repo_dir: Path) -> None:
        for i in range(5):
            (repo_dir / f"f{i}.txt").write_text(str(i), encoding="utf-8")
            git.add()
            git.commit(f"commit {i}")
        entries = git.log(count=3)
        assert len(entries) == 3


class TestGitManagerRollback:
    """Tests for GitManager.rollback."""

    def test_rollback_restores_state(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "original.txt").write_text("v1", encoding="utf-8")
        git.add()
        first_hash = git.commit("first")
        (repo_dir / "original.txt").write_text("v2", encoding="utf-8")
        git.add()
        git.commit("second")
        git.rollback(first_hash)
        assert (repo_dir / "original.txt").read_text(encoding="utf-8") == "v1"

    def test_rollback_invalid_hash_raises(self, git: GitManager) -> None:
        with pytest.raises(GitError):
            git.rollback("0000000000000000000000000000000000000000")


class TestGitManagerHasChanges:
    """Tests for GitManager.has_changes."""

    def test_no_changes_after_commit(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("x", encoding="utf-8")
        git.add()
        git.commit("c")
        assert git.has_changes() is False

    def test_has_changes_with_untracked(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "new.txt").write_text("new", encoding="utf-8")
        assert git.has_changes() is True

    def test_has_changes_with_modified(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("v1", encoding="utf-8")
        git.add()
        git.commit("c")
        (repo_dir / "f.txt").write_text("v2", encoding="utf-8")
        assert git.has_changes() is True


class TestGitManagerStatus:
    """Tests for GitManager.status."""

    def test_status_untracked(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "new.txt").write_text("new", encoding="utf-8")
        entries = git.status()
        assert len(entries) == 1
        assert entries[0]["path"] == "new.txt"
        assert entries[0]["status"] == "untracked"

    def test_status_added(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "a.txt").write_text("a", encoding="utf-8")
        git.add()
        entries = git.status()
        assert any(e["status"] == "added" for e in entries)

    def test_status_modified(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("v1", encoding="utf-8")
        git.add()
        git.commit("c")
        (repo_dir / "f.txt").write_text("v2", encoding="utf-8")
        entries = git.status()
        assert any(e["status"] == "modified" for e in entries)

    def test_status_deleted(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "del.txt").write_text("gone", encoding="utf-8")
        git.add()
        git.commit("c")
        (repo_dir / "del.txt").unlink()
        entries = git.status()
        assert any(e["status"] == "deleted" for e in entries)

    def test_status_empty(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("x", encoding="utf-8")
        git.add()
        git.commit("c")
        assert git.status() == []


class TestGitManagerGetCurrentHash:
    """Tests for GitManager.get_current_hash."""

    def test_get_current_hash(self, git: GitManager, repo_dir: Path) -> None:
        (repo_dir / "f.txt").write_text("x", encoding="utf-8")
        git.add()
        commit_hash = git.commit("c")
        assert git.get_current_hash() == commit_hash


class TestGitError:
    """Tests for the GitError custom exception."""

    def test_git_error_with_stderr(self) -> None:
        err = GitError(message="cmd failed", stderr="fatal: not a git repo")
        assert "cmd failed" in str(err)
        assert "fatal: not a git repo" in str(err)

    def test_git_error_without_stderr(self) -> None:
        err = GitError(message="cmd failed")
        assert "cmd failed" in str(err)


class TestTmpManagerCreate:
    """Tests for TmpManager.create_tmp_dir and get_tmp_dir."""

    def test_create_tmp_dir(self, tmp_mgr: TmpManager) -> None:
        result = tmp_mgr.create_tmp_dir("job1")
        assert result.exists()
        assert result.is_dir()
        assert result.name == "job1"

    def test_create_tmp_dir_already_exists_raises(self, tmp_mgr: TmpManager) -> None:
        tmp_mgr.create_tmp_dir("job1")
        with pytest.raises(FileExistsError):
            tmp_mgr.create_tmp_dir("job1")

    def test_get_tmp_dir(self, tmp_mgr: TmpManager) -> None:
        path = tmp_mgr.get_tmp_dir("job1")
        assert path == tmp_mgr.tmp_root / "job1"

    def test_get_tmp_dir_does_not_create(self, tmp_mgr: TmpManager) -> None:
        path = tmp_mgr.get_tmp_dir("nonexistent")
        assert not path.exists()


class TestTmpManagerMove:
    """Tests for TmpManager.move_to_formal."""

    def test_move_to_formal(self, tmp_mgr: TmpManager, repo_dir: Path) -> None:
        tmp_dir = tmp_mgr.create_tmp_dir("job1")
        (tmp_dir / "file.txt").write_text("data", encoding="utf-8")
        target = repo_dir / "output"
        tmp_mgr.move_to_formal("job1", target)
        assert (target / "file.txt").read_text(encoding="utf-8") == "data"
        assert not tmp_dir.exists()

    def test_move_to_formal_with_subdirs(self, tmp_mgr: TmpManager, repo_dir: Path) -> None:
        tmp_dir = tmp_mgr.create_tmp_dir("job2")
        sub = tmp_dir / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested", encoding="utf-8")
        target = repo_dir / "output"
        tmp_mgr.move_to_formal("job2", target)
        assert (target / "sub" / "nested.txt").read_text(encoding="utf-8") == "nested"

    def test_move_to_formal_nonexistent_raises(self, tmp_mgr: TmpManager, repo_dir: Path) -> None:
        target = repo_dir / "output"
        with pytest.raises(FileNotFoundError):
            tmp_mgr.move_to_formal("missing", target)


class TestTmpManagerCleanup:
    """Tests for TmpManager.cleanup_tmp."""

    def test_cleanup_tmp(self, tmp_mgr: TmpManager) -> None:
        tmp_dir = tmp_mgr.create_tmp_dir("job1")
        (tmp_dir / "file.txt").write_text("data", encoding="utf-8")
        tmp_mgr.cleanup_tmp("job1")
        assert not tmp_dir.exists()

    def test_cleanup_tmp_nonexistent_raises(self, tmp_mgr: TmpManager) -> None:
        with pytest.raises(FileNotFoundError):
            tmp_mgr.cleanup_tmp("missing")


class TestTmpManagerList:
    """Tests for TmpManager.list_tmp_dirs."""

    def test_list_tmp_dirs_empty(self, tmp_mgr: TmpManager) -> None:
        assert tmp_mgr.list_tmp_dirs() == []

    def test_list_tmp_dirs_with_entries(self, tmp_mgr: TmpManager) -> None:
        tmp_mgr.create_tmp_dir("job1")
        tmp_mgr.create_tmp_dir("job2")
        dirs = tmp_mgr.list_tmp_dirs()
        assert sorted(dirs) == ["job1", "job2"]

    def test_list_tmp_dirs_after_cleanup(self, tmp_mgr: TmpManager) -> None:
        tmp_mgr.create_tmp_dir("job1")
        tmp_mgr.create_tmp_dir("job2")
        tmp_mgr.cleanup_tmp("job1")
        dirs = tmp_mgr.list_tmp_dirs()
        assert dirs == ["job2"]
