from vault_app.crypto import decrypt_secret_with_compatibility, encrypt_secret
from vault_app.db import Database
from vault_app.validators import is_valid_site, parse_site, site_exists


class VaultService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_entry(
        self,
        user_id: int,
        site: str,
        login_value: str,
        password_value: str,
        vault_secret: bytes,
        dns_check_enabled: bool = False,
    ) -> tuple[bool, str]:
        site = site.strip()
        login_value = login_value.strip()
        password_value = password_value.strip()

        if not site or not login_value or not password_value:
            return False, "Fill in site, login, and password."

        if not is_valid_site(site):
            return False, "Use a valid site, host, IP, or URL such as github.com or localhost:3000."

        site_info = parse_site(site)
        if site_info is None:
            return False, "Site format is invalid."

        if dns_check_enabled and not site_exists(site):
            return False, "DNS check is enabled and this host is not responding right now."

        encrypted_password = encrypt_secret(password_value, vault_secret)
        self.database.save_entry(
            user_id=user_id,
            site_display=site_info.display,
            site_normalized=site_info.normalized,
            login=login_value,
            password_encrypted=encrypted_password,
            encryption_version=2,
        )
        return True, f"Saved entry for {site_info.display}."

    def list_entries(self, user_id: int):
        return self.database.list_entries(user_id)

    def decrypt_entry_password(self, entry, vault_secret: bytes, legacy_vault_secret: bytes) -> str:
        password_value, _ = decrypt_secret_with_compatibility(
            entry["password_encrypted"],
            vault_secret,
            legacy_vault_secret,
        )
        return password_value

    def migrate_entries_to_modern_crypto(self, user_id: int, vault_secret: bytes, legacy_vault_secret: bytes) -> None:
        for entry in self.database.list_entries(user_id):
            password_value, needs_migration = decrypt_secret_with_compatibility(
                entry["password_encrypted"],
                vault_secret,
                legacy_vault_secret,
            )
            if needs_migration or entry["encryption_version"] != 2:
                self.database.update_entry_password(entry["id"], encrypt_secret(password_value, vault_secret), 2)

    def delete_entry(self, entry_id: int) -> None:
        self.database.delete_entry(entry_id)
