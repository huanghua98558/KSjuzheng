"""SQLite database manager for KS184 automation project.

Provides CRUD access to kuaishou_control.db with WAL mode for concurrent
reads during long-running automation workflows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import DB_PATH

logger = logging.getLogger(__name__)


class DBManager:
    """Thin wrapper around kuaishou_control.db with domain-specific helpers."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        """Open a connection to the SQLite database and enable WAL mode.

        Args:
            db_path: Absolute path to kuaishou_control.db.
                     Defaults to the value loaded from PATHS.json via config.
        """
        self.db_path = db_path
        logger.info("Connecting to database: %s", self.db_path)

        try:
            import time as _t
            t0 = _t.time()
            logger.info("[DBM][pre-connect] %s", self.db_path)
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False,
                                        timeout=30)
            logger.info("[DBM][connected] +%.2fs", _t.time() - t0)
            self.conn.row_factory = sqlite3.Row
            # 先设 busy_timeout (加锁请求时等多久), 不然 PRAGMA 也可能阻塞
            self.conn.execute("PRAGMA busy_timeout=30000;")
            logger.info("[DBM][busy_timeout set] +%.2fs", _t.time() - t0)
            # 查看现 mode, 避免重设 (WAL 设置是持久化的)
            cur_mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
            logger.info("[DBM][mode=%s] +%.2fs", cur_mode, _t.time() - t0)
            if str(cur_mode).lower() != "wal":
                self.conn.execute("PRAGMA journal_mode=WAL;")
                logger.info("[DBM][mode set WAL] +%.2fs", _t.time() - t0)
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            logger.info("[DBM][✅ ready mode=%s] +%.2fs", cur_mode, _t.time() - t0)
        except sqlite3.Error as exc:
            logger.error("Failed to connect to database: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    def get_all_accounts(self) -> list[dict[str, Any]]:
        """Return every row from device_accounts as a list of dicts.

        Columns: id, device_serial, account_id, account_name, browser_port,
                 cookies, login_status, kuaishou_uid, is_active.
        """
        sql = """
            SELECT id, device_serial, account_id, account_name,
                   browser_port, cookies, login_status,
                   kuaishou_uid, is_active
            FROM device_accounts
        """
        try:
            rows = self.conn.execute(sql).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("get_all_accounts failed: %s", exc)
            return []

    def get_account_cookies(self, account_id: int | str) -> Any:
        """Return parsed cookies JSON for a specific account.

        Args:
            account_id: Integer primary key (id) or string account_id (acc_xxx).

        Returns:
            Parsed JSON (usually a dict with ``cookies/creator_cookie/shop_cookie``
            keys, sometimes a list). Empty list on error / missing data.
        """
        if isinstance(account_id, int):
            sql = "SELECT cookies FROM device_accounts WHERE id = ?"
        else:
            sql = "SELECT cookies FROM device_accounts WHERE account_id = ?"
        try:
            row = self.conn.execute(sql, (account_id,)).fetchone()
            if row and row["cookies"]:
                return json.loads(row["cookies"])
            return []
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            logger.error("get_account_cookies(%s) failed: %s", account_id, exc)
            return []

    def mark_cookie_success(self, account_pk: int) -> None:
        """Update ``cookie_last_success_at`` for a successful cookie-bearing API call."""
        sql = "UPDATE device_accounts SET cookie_last_success_at = ? WHERE id = ?"
        try:
            self.conn.execute(sql, (datetime.now(timezone.utc).isoformat(), account_pk))
            self.conn.commit()
        except sqlite3.Error as exc:
            logger.error("mark_cookie_success(%s) failed: %s", account_pk, exc)

    def get_logged_in_accounts(self) -> list[dict[str, Any]]:
        """Return accounts that are currently logged in with valid cookies."""
        sql = """
            SELECT id, device_serial, account_id, account_name,
                   browser_port, cookies, login_status,
                   kuaishou_uid, is_active
            FROM device_accounts
            WHERE login_status = 'logged_in'
              AND cookies IS NOT NULL
              AND cookies != ''
        """
        try:
            rows = self.conn.execute(sql).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("get_logged_in_accounts failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Drama link management
    # ------------------------------------------------------------------

    def get_drama_links(self, status: str = "pending") -> list[dict[str, Any]]:
        """Return drama links filtered by status.

        Args:
            status: One of 'pending', 'downloading', 'completed', 'failed'.
        """
        sql = "SELECT * FROM drama_links WHERE status = ?"
        try:
            rows = self.conn.execute(sql, (status,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("get_drama_links(status=%s) failed: %s", status, exc)
            return []

    def add_drama_link(
        self,
        drama_name: str,
        drama_url: str,
        source_file: str = "manual",
        link_mode: str = "firefly",
    ) -> int | None:
        """Insert a new drama link and return its row id.

        Args:
            drama_name: Human-readable drama title.
            drama_url: URL to the drama resource.
            source_file: Where this link came from.
            link_mode: Extraction mode ('firefly', 'direct', etc.).

        Returns:
            The new row id, or None on failure.
        """
        sql = """
            INSERT INTO drama_links (drama_name, drama_url, source_file, link_mode, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self.conn.execute(sql, (drama_name, drama_url, source_file, link_mode, now))
            self.conn.commit()
            logger.info("Added drama link: %s (id=%d)", drama_name, cursor.lastrowid)
            return cursor.lastrowid
        except sqlite3.Error as exc:
            logger.error("add_drama_link failed: %s", exc)
            self.conn.rollback()
            return None

    def update_drama_link_status(self, drama_id: int, status: str) -> bool:
        """Update the status of a drama link.

        Args:
            drama_id: Primary key of the drama_links row.
            status: New status value.

        Returns:
            True if a row was updated, False otherwise.
        """
        sql = "UPDATE drama_links SET status = ? WHERE id = ?"
        try:
            cursor = self.conn.execute(sql, (status, drama_id))
            self.conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Drama link %d status -> %s", drama_id, status)
            else:
                logger.warning("Drama link %d not found for status update", drama_id)
            return updated
        except sqlite3.Error as exc:
            logger.error("update_drama_link_status(%d) failed: %s", drama_id, exc)
            self.conn.rollback()
            return False

    # ------------------------------------------------------------------
    # Execution logs
    # ------------------------------------------------------------------

    def log_execution(
        self,
        kuaishou_uid: str,
        kuaishou_name: str,
        device_serial: str,
        drama_name: str,
        drama_url: str,
        status: str,
        video_path: str = "",
    ) -> int | None:
        """Record an automation execution event.

        Args:
            kuaishou_uid: Kuaishou user id that performed the action.
            kuaishou_name: Display name of the account.
            device_serial: Device identifier.
            drama_name: Drama title involved.
            drama_url: Drama URL involved.
            status: Outcome status ('success', 'failed', etc.).
            video_path: Local path to the video file, if applicable.

        Returns:
            The new log row id, or None on failure.
        """
        sql = """
            INSERT INTO account_drama_execution_logs
                (kuaishou_uid, kuaishou_name, device_serial,
                 drama_name, drama_url, status, video_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = self.conn.execute(
                sql,
                (kuaishou_uid, kuaishou_name, device_serial,
                 drama_name, drama_url, status, video_path, now),
            )
            self.conn.commit()
            logger.info(
                "Logged execution: uid=%s drama=%s status=%s",
                kuaishou_uid, drama_name, status,
            )
            return cursor.lastrowid
        except sqlite3.Error as exc:
            logger.error("log_execution failed: %s", exc)
            self.conn.rollback()
            return None

    def get_execution_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent execution log entries.

        Args:
            limit: Maximum number of rows to return (newest first).
        """
        sql = """
            SELECT * FROM account_drama_execution_logs
            ORDER BY created_at DESC
            LIMIT ?
        """
        try:
            rows = self.conn.execute(sql, (limit,)).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("get_execution_logs failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Download cache
    # ------------------------------------------------------------------

    def get_download_cache(self) -> list[dict[str, Any]]:
        """Return all entries from the download_cache table."""
        sql = "SELECT * FROM download_cache"
        try:
            rows = self.conn.execute(sql).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("get_download_cache failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    def __enter__(self) -> DBManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        self.close()
