"""TOTP (RFC 6238) and single-use recovery codes."""

import hashlib
import hmac
import secrets
from datetime import datetime

import pyotp

RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account: str, issuer: str = "Hivora") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def totp_step(secret: str, code: str, at: datetime) -> int | None:
    """The 30 s step the code belongs to (previous, current or next: clock drift), or None.

    Callers refuse a step at or before the last one accepted: a code works once.
    """
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = totp.timecode(at)
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def verify_totp(secret: str, code: str, at: datetime) -> bool:
    return totp_step(secret, code, at) is not None


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Codes like ``ABCD-EFGH-JKLM-NPQR`` (80 bits of entropy each)."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(16))
        codes.append("-".join(raw[i : i + 4] for i in range(0, 16, 4)))
    return codes


def _normalize(code: str) -> str:
    return code.strip().upper().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    # High-entropy random codes: a fast hash is sufficient (no brute force possible).
    return hashlib.sha256(_normalize(code).encode()).hexdigest()


def match_recovery_code(code: str, hashes: list[str]) -> int | None:
    """Index of the matching hash, so the caller can consume (remove) it."""
    candidate = hash_recovery_code(code)
    for i, stored in enumerate(hashes):
        if hmac.compare_digest(candidate, stored):
            return i
    return None
