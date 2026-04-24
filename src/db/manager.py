from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator


class DatabaseManager:
    """Manages SQLite database operations for the Librarian system.

    Provides thread-safe CRUD operations for skills, skills_links,
    and tools_ref_count tables. Uses a connection-per-operation pattern
    with PRAGMA foreign_keys enabled.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "./data/librarian.db") -> None:
        """Initialize the DatabaseManager.

        Args:
            db_path: File path to the SQLite database. Use ':memory:' for
                in-memory databases (useful for testing).
        """
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._persistent_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(db_path, check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional database connection as a context manager.

        For in-memory databases, reuses a single persistent connection.
        For file databases, creates a new connection per operation.
        Enables foreign keys and sets row_factory to sqlite3.Row for
        dict-like access. The connection is automatically committed on
        success or rolled back on exception.

        Yields:
            A sqlite3.Connection with foreign keys enabled.

        Raises:
            sqlite3.Error: If the connection cannot be established.
        """
        if self._persistent_conn is not None:
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            except Exception:
                self._persistent_conn.rollback()
                raise
            return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create the skills, skills_links, and tools_ref_count tables.

        Creates the database file's parent directory if it does not exist.
        Idempotent — safe to call multiple times.

        Raises:
            sqlite3.Error: If table creation fails.
        """
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    skill_name VARCHAR(100) PRIMARY KEY,
                    last_update_at TIMESTAMP,
                    last_use_at TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name VARCHAR(100),
                    link_path VARCHAR(500),
                    last_update_at TIMESTAMP,
                    FOREIGN KEY (skill_name) REFERENCES skills(skill_name) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tools_ref_count (
                    tool_name VARCHAR(100) PRIMARY KEY,
                    ref_count INTEGER
                )
            """)

    @staticmethod
    def _now() -> str:
        """Return the current UTC timestamp as an ISO format string.

        Returns:
            ISO 8601 formatted UTC datetime string.
        """
        return datetime.now(timezone.utc).isoformat()

    def upsert_skill(
        self,
        skill_name: str,
        last_update_at: datetime | None = None,
        last_use_at: datetime | None = None,
    ) -> None:
        """Insert or update a skill record.

        Args:
            skill_name: Unique name of the skill.
            last_update_at: Timestamp of last update. Defaults to now.
            last_use_at: Timestamp of last use. Defaults to now.
        """
        update_at = (last_update_at or datetime.now(timezone.utc)).isoformat()
        use_at = (last_use_at or datetime.now(timezone.utc)).isoformat()
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO skills (skill_name, last_update_at, last_use_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        last_update_at = excluded.last_update_at,
                        last_use_at = excluded.last_use_at
                    """,
                    (skill_name, update_at, use_at),
                )

    def get_skill(self, skill_name: str) -> dict | None:
        """Retrieve a single skill by name.

        Args:
            skill_name: Unique name of the skill.

        Returns:
            A dict with skill_name, last_update_at, last_use_at keys,
            or None if not found.
        """
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM skills WHERE skill_name = ?", (skill_name,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_skills(self) -> list[dict]:
        """Retrieve all skill records.

        Returns:
            A list of dicts with skill_name, last_update_at, last_use_at keys.
        """
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM skills").fetchall()
            return [dict(r) for r in rows]

    def delete_skill(self, skill_name: str) -> None:
        """Delete a skill and its associated links (cascade).

        Args:
            skill_name: Unique name of the skill to delete.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute("DELETE FROM skills WHERE skill_name = ?", (skill_name,))

    def update_skill_timestamps(
        self,
        skill_name: str,
        last_update_at: datetime | None = None,
        last_use_at: datetime | None = None,
    ) -> None:
        """Update timestamps for an existing skill.

        Only updates fields that are provided (non-None).

        Args:
            skill_name: Unique name of the skill.
            last_update_at: New last_update_at value, or None to skip.
            last_use_at: New last_use_at value, or None to skip.
        """
        parts: list[str] = []
        params: list[str] = []
        if last_update_at is not None:
            parts.append("last_update_at = ?")
            params.append(last_update_at.isoformat())
        if last_use_at is not None:
            parts.append("last_use_at = ?")
            params.append(last_use_at.isoformat())
        if not parts:
            return
        params.append(skill_name)
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    f"UPDATE skills SET {', '.join(parts)} WHERE skill_name = ?",
                    params,
                )

    def search_skills(self, query: str) -> list[dict]:
        """Search skills by name using a case-insensitive LIKE query.

        Args:
            query: Search term to match against skill_name.

        Returns:
            A list of matching skill dicts.
        """
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM skills WHERE skill_name LIKE ?",
                (f"%{query}%",),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_skill_link(
        self,
        skill_name: str,
        link_path: str,
        last_update_at: datetime | None = None,
    ) -> None:
        """Add a link association for a skill.

        Args:
            skill_name: Name of the skill the link belongs to.
            link_path: Path identifying the linked agent or resource.
            last_update_at: Timestamp of the link. Defaults to now.
        """
        update_at = (last_update_at or datetime.now(timezone.utc)).isoformat()
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO skills_links (skill_name, link_path, last_update_at)
                    VALUES (?, ?, ?)
                    """,
                    (skill_name, link_path, update_at),
                )

    def get_skill_links(self, skill_name: str) -> list[dict]:
        """Retrieve all links for a specific skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            A list of link dicts with id, skill_name, link_path, last_update_at.
        """
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM skills_links WHERE skill_name = ?",
                (skill_name,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_links(self) -> list[dict]:
        """Retrieve all skill links.

        Returns:
            A list of all link dicts.
        """
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM skills_links").fetchall()
            return [dict(r) for r in rows]

    def delete_skill_links(self, skill_name: str) -> None:
        """Delete all links for a specific skill.

        Args:
            skill_name: Name of the skill whose links should be removed.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    "DELETE FROM skills_links WHERE skill_name = ?",
                    (skill_name,),
                )

    def update_link_timestamp(
        self, skill_name: str, link_path: str, last_update_at: datetime
    ) -> None:
        """Update the timestamp of a specific skill link.

        Args:
            skill_name: Name of the skill.
            link_path: Path of the link to update.
            last_update_at: New timestamp value.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    UPDATE skills_links
                    SET last_update_at = ?
                    WHERE skill_name = ? AND link_path = ?
                    """,
                    (last_update_at.isoformat(), skill_name, link_path),
                )

    def upsert_tool_ref(self, tool_name: str, ref_count: int) -> None:
        """Insert or update a tool's reference count.

        Args:
            tool_name: Name of the tool.
            ref_count: The reference count to set.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tools_ref_count (tool_name, ref_count)
                    VALUES (?, ?)
                    ON CONFLICT(tool_name) DO UPDATE SET ref_count = excluded.ref_count
                    """,
                    (tool_name, ref_count),
                )

    def get_tool_ref(self, tool_name: str) -> int | None:
        """Get the reference count for a tool.

        Args:
            tool_name: Name of the tool.

        Returns:
            The reference count, or None if the tool is not tracked.
        """
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT ref_count FROM tools_ref_count WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            return row["ref_count"] if row else None

    def get_all_tools_refs(self) -> list[dict]:
        """Retrieve all tool reference counts.

        Returns:
            A list of dicts with tool_name and ref_count keys.
        """
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM tools_ref_count").fetchall()
            return [dict(r) for r in rows]

    def increment_tool_ref(self, tool_name: str) -> None:
        """Increment a tool's reference count by 1.

        If the tool does not exist, it is created with ref_count = 1.

        Args:
            tool_name: Name of the tool.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tools_ref_count (tool_name, ref_count)
                    VALUES (?, 1)
                    ON CONFLICT(tool_name) DO UPDATE SET ref_count = ref_count + 1
                    """,
                    (tool_name,),
                )

    def decrement_tool_ref(self, tool_name: str) -> int:
        """Decrement a tool's reference count by 1.

        If the count reaches 0, the tool record is automatically deleted.

        Args:
            tool_name: Name of the tool.

        Returns:
            The new reference count after decrement (0 means deleted).
        """
        with self._write_lock:
            with self.get_connection() as conn:
                row = conn.execute(
                    "SELECT ref_count FROM tools_ref_count WHERE tool_name = ?",
                    (tool_name,),
                ).fetchone()
                if row is None:
                    return 0
                current = row["ref_count"]
                new_count = current - 1
                if new_count <= 0:
                    conn.execute(
                        "DELETE FROM tools_ref_count WHERE tool_name = ?",
                        (tool_name,),
                    )
                    return 0
                conn.execute(
                    "UPDATE tools_ref_count SET ref_count = ? WHERE tool_name = ?",
                    (new_count, tool_name),
                )
                return new_count

    def delete_tool_ref(self, tool_name: str) -> None:
        """Delete a tool reference count record.

        Args:
            tool_name: Name of the tool to remove.
        """
        with self._write_lock:
            with self.get_connection() as conn:
                conn.execute(
                    "DELETE FROM tools_ref_count WHERE tool_name = ?",
                    (tool_name,),
                )

    def close(self) -> None:
        """Close any persistent resources held by the manager.

        Closes the persistent in-memory connection if one exists.
        """
        if self._persistent_conn is not None:
            self._persistent_conn.close()
            self._persistent_conn = None
