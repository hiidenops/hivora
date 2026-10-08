"""Password and username rules (hashing itself is Argon2id, in `crypto.passwords`)."""

import re
import secrets
from functools import cache

from hivora.core.errors import ValidationError
from hivora.crypto.passwords import hash_password

DEFAULT_ADMIN = "admin"
MIN_PASSWORD_LENGTH = 10
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class WeakPasswordError(ValidationError):
    code = "weak_password"


@cache
def dummy_hash() -> str:
    """Verified when the user does not exist, so timing does not reveal usernames."""
    return hash_password(secrets.token_hex(16))


def check_password_policy(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError("password too short", min_length=MIN_PASSWORD_LENGTH)
    if password.lower() in (username.lower(), DEFAULT_ADMIN):
        raise WeakPasswordError("password too easy to guess")


def validate_username(username: str) -> str:
    username = username.strip().lower()
    if not _USERNAME.match(username):
        raise ValidationError("invalid username", field="username")
    return username
