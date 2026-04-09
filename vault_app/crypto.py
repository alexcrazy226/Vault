import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vault_app.config import ENC_ITERATIONS, HASH_ITERATIONS


MODERN_TOKEN_PREFIX = "v2:"
LEGACY_SALT_SIZE = 16
MODERN_NONCE_SIZE = 12


def pbkdf2_key(secret: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations, dklen=32)


def hash_password(password: str, salt: bytes) -> str:
    return pbkdf2_key(password, salt, HASH_ITERATIONS).hex()


def derive_vault_secret(password_hash: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password_hash.encode("utf-8"), salt, ENC_ITERATIONS, dklen=32)


def derive_legacy_vault_secret(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ENC_ITERATIONS, dklen=32)


def _derive_entry_key(vault_secret: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", vault_secret, salt, ENC_ITERATIONS, dklen=32)


def _build_legacy_keystream(key: bytes, size: int) -> bytes:
    stream = bytearray()
    counter = 0

    while len(stream) < size:
        block = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1

    return bytes(stream[:size])


def encrypt_secret(secret: str, vault_secret: bytes) -> str:
    salt = os.urandom(LEGACY_SALT_SIZE)
    nonce = os.urandom(MODERN_NONCE_SIZE)
    key = _derive_entry_key(vault_secret, salt)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), None)
    payload = base64.urlsafe_b64encode(salt + nonce + ciphertext).decode("ascii")
    return f"{MODERN_TOKEN_PREFIX}{payload}"


def decrypt_secret_with_compatibility(token: str, vault_secret: bytes, legacy_vault_secret: bytes = b"") -> tuple[str, bool]:
    if token.startswith(MODERN_TOKEN_PREFIX):
        return _decrypt_modern_secret(token, vault_secret), False

    try:
        return _decrypt_legacy_secret(token, vault_secret), True
    except ValueError:
        if legacy_vault_secret:
            return _decrypt_legacy_secret(token, legacy_vault_secret), True
        raise


def _decrypt_modern_secret(token: str, vault_secret: bytes) -> str:
    payload = token[len(MODERN_TOKEN_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid encrypted payload.") from exc

    salt = raw[:LEGACY_SALT_SIZE]
    nonce = raw[LEGACY_SALT_SIZE : LEGACY_SALT_SIZE + MODERN_NONCE_SIZE]
    ciphertext = raw[LEGACY_SALT_SIZE + MODERN_NONCE_SIZE :]
    key = _derive_entry_key(vault_secret, salt)

    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise ValueError("Stored secret integrity check failed.") from exc

    return plaintext.decode("utf-8")


def _decrypt_legacy_secret(token: str, vault_secret: bytes) -> str:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid encrypted payload.") from exc

    salt = raw[:16]
    signature = raw[16:48]
    ciphertext = raw[48:]
    key = hashlib.pbkdf2_hmac("sha256", vault_secret, salt, ENC_ITERATIONS, dklen=32)
    expected = hmac.new(key, ciphertext, hashlib.sha256).digest()

    if not hmac.compare_digest(signature, expected):
        raise ValueError("Stored secret integrity check failed.")

    keystream = _build_legacy_keystream(key, len(ciphertext))
    payload = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    return payload.decode("utf-8")
