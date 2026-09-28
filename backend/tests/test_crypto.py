import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
import pytest

from hivora.crypto.cipher import (
    CryptoError,
    Purpose,
    SecretBox,
    load_or_create_master_key,
)
from hivora.crypto.passwords import hash_password, needs_rehash, verify_password
from hivora.crypto.totp import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    match_recovery_code,
    totp_step,
    verify_totp,
)


def test_password_roundtrip() -> None:
    h = hash_password("correct horse")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")
    assert not needs_rehash(h)


def test_totp_accepts_adjacent_steps_only() -> None:
    secret = generate_totp_secret()
    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    code = pyotp.TOTP(secret).at(now)
    assert verify_totp(secret, code, now + timedelta(seconds=30))
    assert not verify_totp(secret, code, now + timedelta(minutes=5))
    assert not verify_totp(secret, "abc123", now)
    step = totp_step(secret, code, now)
    assert step is not None and totp_step(secret, code, now + timedelta(seconds=30)) == step


def test_recovery_codes() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    hashes = [hash_recovery_code(c) for c in codes]
    assert match_recovery_code(codes[3].lower().replace("-", " "), hashes) == 3
    assert match_recovery_code("AAAA-AAAA-AAAA-AAAA", hashes) is None


def test_master_key_created_0600_and_reloaded(tmp_path: Path) -> None:
    path = tmp_path / "data" / "secret.key"
    key = load_or_create_master_key(path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert load_or_create_master_key(path) == key


def test_master_key_refuses_loose_permissions(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    load_or_create_master_key(path)
    os.chmod(path, 0o644)
    with pytest.raises(CryptoError):
        load_or_create_master_key(path)


def test_secret_box_binds_context_and_purpose() -> None:
    box = SecretBox(os.urandom(32))
    sealed = box.seal(Purpose.APP_SECRET, "hunter2", "app:1:admin_password")
    assert b"hunter2" not in sealed.ciphertext
    assert box.open(Purpose.APP_SECRET, sealed, "app:1:admin_password") == "hunter2"
    with pytest.raises(CryptoError):
        box.open(Purpose.APP_SECRET, sealed, "app:2:admin_password")
    with pytest.raises(CryptoError):
        box.open(Purpose.REGISTRY, sealed, "app:1:admin_password")
    with pytest.raises(CryptoError):
        SecretBox(os.urandom(32)).open(Purpose.APP_SECRET, sealed, "app:1:admin_password")
