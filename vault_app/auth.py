import os
import sqlite3
import time
from dataclasses import dataclass

from vault_app.config import LOGIN_LOCKOUT_SECONDS, LOGIN_LOCKOUT_THRESHOLD
from vault_app.crypto import (
    derive_legacy_vault_secret,
    derive_vault_secret,
    encrypt_secret,
    hash_password,
)
from vault_app.db import Database
from vault_app.notifier import TelegramNotifier


@dataclass
class UserSession:
    user_id: int
    username: str
    avatar: bytes | None
    theme_name: str
    music_volume: float
    site_exists_check_enabled: bool
    background_choice: str
    vault_secret: bytes
    legacy_vault_secret: bytes


@dataclass
class AuthResult:
    success: bool
    message: str
    session: UserSession | None = None
    locked_seconds: int = 0
    show_breach_popup: bool = False


class AuthService:
    def __init__(self, database: Database, notifier: TelegramNotifier) -> None:
        self.database = database
        self.notifier = notifier
        self.failed_login_count = 0
        self.locked_until = 0.0

    def register_user(
        self,
        username: str,
        password: str,
        avatar: bytes | None,
        theme_name: str,
        music_volume: float,
        site_exists_check_enabled: bool = True,
        background_choice: str = "",
    ) -> AuthResult:
        username = username.strip()
        password = password.strip()

        if len(username) < 3:
            return AuthResult(False, "Username must be at least 3 characters.")

        if len(password) < 8:
            return AuthResult(False, "Password must be at least 8 characters.")

        salt = os.urandom(16)
        password_hash = hash_password(password, salt)

        try:
            self.database.create_user(
                username,
                password_hash,
                salt,
                avatar,
                theme_name,
                music_volume,
                site_exists_check_enabled=site_exists_check_enabled,
                background_choice=background_choice,
            )
        except sqlite3.IntegrityError:
            return AuthResult(False, "This username is already taken.")

        return AuthResult(True, "Account created. You can log in now.")

    def login_user(self, username: str, password: str) -> AuthResult:
        remaining = self._lockout_remaining()
        if remaining > 0:
            return AuthResult(False, f"Too many failed attempts. Try again in {remaining} seconds.", locked_seconds=remaining)

        username = username.strip()
        password = password.strip()
        row = self.database.get_user_by_username(username)

        if row is None:
            return self._handle_failed_login(username, "user_not_found", "User not found.")

        password_hash = hash_password(password, row["password_salt"])
        if password_hash != row["password_hash"]:
            return self._handle_failed_login(username, "wrong_password", "Wrong password.", show_breach_popup=True)

        self.failed_login_count = 0
        self.locked_until = 0.0
        session = UserSession(
            user_id=row["id"],
            username=row["username"],
            avatar=row["avatar"],
            theme_name=row["theme_name"],
            music_volume=row["music_volume"],
            site_exists_check_enabled=bool(row["site_exists_check_enabled"]),
            background_choice=row["background_choice"] or "",
            vault_secret=derive_vault_secret(password_hash, row["password_salt"]),
            legacy_vault_secret=derive_legacy_vault_secret(password, row["password_salt"]),
        )
        return AuthResult(True, "Login successful.", session=session)

    def update_settings(
        self,
        user_id: int,
        current_vault_secret: bytes,
        current_legacy_vault_secret: bytes,
        username: str,
        new_password: str,
        avatar: bytes | None,
        theme_name: str,
        music_volume: float,
        site_exists_check_enabled: bool,
        background_choice: str,
        entries: list,
        decrypt_entry_password,
    ) -> tuple[bool, str, bytes]:
        username = username.strip()
        new_password = new_password.strip()

        if len(username) < 3:
            return False, "Username must be at least 3 characters.", current_vault_secret

        row = self.database.get_user_by_id(user_id)
        if row is None:
            return False, "User not found.", current_vault_secret

        password_hash = row["password_hash"]
        password_salt = row["password_salt"]
        new_vault_secret = current_vault_secret
        reencrypted_entries: list[tuple[int, str, int]] = []

        if new_password:
            if len(new_password) < 8:
                return False, "Password must be at least 8 characters.", current_vault_secret

            decrypted_entries = []
            for entry in entries:
                decrypted_entries.append((entry["id"], decrypt_entry_password(entry, current_vault_secret, current_legacy_vault_secret)))

            password_salt = os.urandom(16)
            password_hash = hash_password(new_password, password_salt)
            new_vault_secret = derive_vault_secret(password_hash, password_salt)

            for entry_id, plaintext in decrypted_entries:
                reencrypted_entries.append((entry_id, encrypt_secret(plaintext, new_vault_secret), 2))

        try:
            self.database.update_user_settings(
                user_id=user_id,
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                avatar=avatar,
                theme_name=theme_name,
                music_volume=music_volume,
                site_exists_check_enabled=site_exists_check_enabled,
                background_choice=background_choice,
                reencrypted_entries=reencrypted_entries,
            )
        except sqlite3.IntegrityError:
            return False, "This username is already in use.", current_vault_secret

        return True, "Settings updated.", new_vault_secret

    def _handle_failed_login(self, username: str, reason: str, message: str, show_breach_popup: bool = False) -> AuthResult:
        self.failed_login_count += 1
        if self.failed_login_count >= LOGIN_LOCKOUT_THRESHOLD:
            self.locked_until = time.monotonic() + LOGIN_LOCKOUT_SECONDS
            message = f"Too many failed attempts. Try again in {LOGIN_LOCKOUT_SECONDS} seconds."

        self.notifier.notify_failed_login(username, reason, self.failed_login_count)
        return AuthResult(
            False,
            message,
            locked_seconds=self._lockout_remaining(),
            show_breach_popup=show_breach_popup,
        )

    def _lockout_remaining(self) -> int:
        remaining = int(self.locked_until - time.monotonic())
        return max(0, remaining)
