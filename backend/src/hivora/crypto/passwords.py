"""Password hashing with Argon2id (salt embedded in the encoded hash)."""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# RFC 9106 "second recommended option" (64 MiB): safe on a Raspberry Pi,
# and login is rate limited anyway.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4, type=Type.ID)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
