"""AES-256-GCM encryption of secrets at rest, keyed by a master key on disk.

Each purpose (app secrets, registry credentials, TOTP seeds) gets its own
subkey derived with HKDF, and callers bind ciphertexts to their context
through associated data (e.g. ``app:42:admin_password``) so that a
ciphertext cannot be moved to another row.
"""

import os
import secrets
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from hivora.core.errors import HivoraError

MASTER_KEY_BYTES = 32
NONCE_BYTES = 12


class CryptoError(HivoraError):
    code = "crypto_error"


class Purpose(StrEnum):
    APP_SECRET = "app-secret"  # noqa: S105 (purpose label, not a secret)
    REGISTRY = "registry"
    TOTP = "totp"
    SETTING = "setting"  # secret global settings (e.g. third-party API keys)


@dataclass(frozen=True, slots=True)
class Sealed:
    nonce: bytes
    ciphertext: bytes


def load_or_create_master_key(path: Path) -> bytes:
    """Read the master key, creating it (mode 0600) on first start.

    Refuses a key readable by group or others: it protects every secret.
    """
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise CryptoError(f"{path} must not be accessible by group/others (mode {mode:o})")
        key = path.read_bytes()
        if len(key) != MASTER_KEY_BYTES:
            raise CryptoError(f"{path} has an invalid length")
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(MASTER_KEY_BYTES)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class SecretBox:
    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != MASTER_KEY_BYTES:
            raise CryptoError("master key must be 32 bytes")
        self._aead = {p: AESGCM(self._derive(master_key, p)) for p in Purpose}

    @staticmethod
    def _derive(master_key: bytes, purpose: Purpose) -> bytes:
        hkdf = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=f"hivora/{purpose}".encode()
        )
        return hkdf.derive(master_key)

    def seal(self, purpose: Purpose, plaintext: str, context: str) -> Sealed:
        nonce = secrets.token_bytes(NONCE_BYTES)
        ct = self._aead[purpose].encrypt(nonce, plaintext.encode(), context.encode())
        return Sealed(nonce, ct)

    def open(self, purpose: Purpose, sealed: Sealed, context: str) -> str:
        try:
            pt = self._aead[purpose].decrypt(sealed.nonce, sealed.ciphertext, context.encode())
        except InvalidTag:
            raise CryptoError("decryption failed (wrong key, context or tampered data)") from None
        return pt.decode()
