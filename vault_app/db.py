import logging
import sqlite3
from pathlib import Path

from vault_app.validators import coerce_legacy_site


logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_db()

    def close(self) -> None:
        self.conn.close()

    def _init_db(self) -> None:
        self._init_users_table()
        self._init_vault_entries_table()

    def _init_users_table(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                avatar BLOB,
                theme_name TEXT NOT NULL DEFAULT 'Mr. Robot',
                music_volume REAL NOT NULL DEFAULT 0.35,
                site_exists_check_enabled INTEGER NOT NULL DEFAULT 1,
                background_choice TEXT NOT NULL DEFAULT ''
            )
            """
        )
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(users)").fetchall()}
            if "avatar" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN avatar BLOB")
            if "theme_name" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN theme_name TEXT NOT NULL DEFAULT 'Mr. Robot'")
            if "music_volume" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN music_volume REAL NOT NULL DEFAULT 0.35")
            if "site_exists_check_enabled" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN site_exists_check_enabled INTEGER NOT NULL DEFAULT 1")
            if "background_choice" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN background_choice TEXT NOT NULL DEFAULT ''")

    def _init_vault_entries_table(self) -> None:
        if not self._table_exists("vault_entries"):
            with self.conn:
                self._create_final_vault_entries_table("vault_entries")
            return

        if self._vault_entries_is_final():
            return

        logger.info("Running vault_entries schema migration.")
        self._migrate_vault_entries_table()

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _vault_entries_is_final(self) -> bool:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(vault_entries)").fetchall()}
        expected = {"id", "user_id", "site_display", "site_normalized", "login", "password_encrypted", "encryption_version"}
        if not expected.issubset(columns):
            return False

        for index in self.conn.execute("PRAGMA index_list(vault_entries)").fetchall():
            if not index["unique"]:
                continue
            indexed_columns = [row["name"] for row in self.conn.execute(f"PRAGMA index_info({index['name']})").fetchall()]
            if indexed_columns == ["user_id", "site_normalized", "login"]:
                return True
        return False

    def _create_final_vault_entries_table(self, table_name: str) -> None:
        self.conn.execute(
            f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                site_display TEXT NOT NULL,
                site_normalized TEXT NOT NULL,
                login TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                encryption_version INTEGER NOT NULL DEFAULT 2,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, site_normalized, login)
            )
            """
        )

    def _migrate_vault_entries_table(self) -> None:
        with self.conn:
            self._create_final_vault_entries_table("vault_entries_new")
            rows = self.conn.execute("SELECT * FROM vault_entries ORDER BY id").fetchall()
            used_keys: set[tuple[int, str, str]] = set()

            for row in rows:
                site_source = row["site_display"] if "site_display" in row.keys() else row["site"]
                site_info = coerce_legacy_site(site_source)
                login_value = (row["login"] or "").strip() or "account"
                unique_login = self._dedupe_login(row["user_id"], site_info.normalized, login_value, used_keys)
                encryption_version = (
                    row["encryption_version"]
                    if "encryption_version" in row.keys()
                    else (2 if str(row["password_encrypted"]).startswith("v2:") else 1)
                )

                self.conn.execute(
                    """
                    INSERT INTO vault_entries_new (
                        id,
                        user_id,
                        site_display,
                        site_normalized,
                        login,
                        password_encrypted,
                        encryption_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["user_id"],
                        site_info.display,
                        site_info.normalized,
                        unique_login,
                        row["password_encrypted"],
                        encryption_version,
                    ),
                )

            self.conn.execute("DROP TABLE vault_entries")
            self.conn.execute("ALTER TABLE vault_entries_new RENAME TO vault_entries")

    def _dedupe_login(self, user_id: int, site_normalized: str, login_value: str, used_keys: set[tuple[int, str, str]]) -> str:
        candidate = login_value
        suffix = 2
        key = (user_id, site_normalized, candidate.casefold())
        while key in used_keys:
            candidate = f"{login_value} ({suffix})"
            key = (user_id, site_normalized, candidate.casefold())
            suffix += 1
        used_keys.add(key)
        return candidate

    def get_user_by_username(self, username: str):
        return self.conn.execute(
            """
            SELECT id, username, password_hash, password_salt, avatar, theme_name, music_volume, site_exists_check_enabled, background_choice
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    def get_user_by_id(self, user_id: int):
        return self.conn.execute(
            """
            SELECT id, username, password_hash, password_salt, avatar, theme_name, music_volume, site_exists_check_enabled, background_choice
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    def create_user(
        self,
        username: str,
        password_hash: str,
        password_salt: bytes,
        avatar: bytes | None,
        theme_name: str,
        music_volume: float,
        site_exists_check_enabled: bool = True,
        background_choice: str = "",
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO users (
                    username,
                    password_hash,
                    password_salt,
                    avatar,
                    theme_name,
                    music_volume,
                    site_exists_check_enabled,
                    background_choice
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    password_hash,
                    password_salt,
                    avatar,
                    theme_name,
                    music_volume,
                    1 if site_exists_check_enabled else 0,
                    background_choice,
                ),
            )

    def update_user_settings(
        self,
        user_id: int,
        username: str,
        password_hash: str,
        password_salt: bytes,
        avatar: bytes | None,
        theme_name: str,
        music_volume: float,
        site_exists_check_enabled: bool,
        background_choice: str,
        reencrypted_entries: list[tuple[int, str, int]] | None = None,
    ) -> None:
        with self.conn:
            for entry_id, encrypted_password, encryption_version in reencrypted_entries or []:
                self.conn.execute(
                    """
                    UPDATE vault_entries
                    SET password_encrypted = ?, encryption_version = ?
                    WHERE id = ?
                    """,
                    (encrypted_password, encryption_version, entry_id),
                )

            self.conn.execute(
                """
                UPDATE users
                SET username = ?, password_hash = ?, password_salt = ?, avatar = ?, theme_name = ?, music_volume = ?, site_exists_check_enabled = ?, background_choice = ?
                WHERE id = ?
                """,
                (
                    username,
                    password_hash,
                    password_salt,
                    avatar,
                    theme_name,
                    music_volume,
                    1 if site_exists_check_enabled else 0,
                    background_choice,
                    user_id,
                ),
            )

    def list_entries(self, user_id: int):
        return self.conn.execute(
            """
            SELECT id, site_display, site_normalized, login, password_encrypted, encryption_version
            FROM vault_entries
            WHERE user_id = ?
            ORDER BY site_display COLLATE NOCASE, login COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()

    def save_entry(
        self,
        user_id: int,
        site_display: str,
        site_normalized: str,
        login: str,
        password_encrypted: str,
        encryption_version: int = 2,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO vault_entries (
                    user_id,
                    site_display,
                    site_normalized,
                    login,
                    password_encrypted,
                    encryption_version
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, site_normalized, login) DO UPDATE SET
                    site_display = excluded.site_display,
                    password_encrypted = excluded.password_encrypted,
                    encryption_version = excluded.encryption_version
                """,
                (user_id, site_display, site_normalized, login, password_encrypted, encryption_version),
            )

    def delete_entry(self, entry_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM vault_entries WHERE id = ?", (entry_id,))

    def update_entry_password(self, entry_id: int, password_encrypted: str, encryption_version: int = 2) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE vault_entries
                SET password_encrypted = ?, encryption_version = ?
                WHERE id = ?
                """,
                (password_encrypted, encryption_version, entry_id),
            )
