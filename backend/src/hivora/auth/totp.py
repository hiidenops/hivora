"""Second factor: TOTP secrets (sealed), codes accepted once, recovery codes."""

from dataclasses import dataclass

from hivora.auth.models import User
from hivora.core.clock import Clock
from hivora.core.errors import HivoraError
from hivora.crypto.cipher import Purpose, Sealed, SecretBox
from hivora.crypto.totp import (
    generate_totp_secret,
    match_recovery_code,
    provisioning_uri,
    totp_step,
)


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    secret: str
    uri: str


class TotpGuard:
    def __init__(self, box: SecretBox, clock: Clock) -> None:
        self.box = box
        self.clock = clock
        # ponytail: last TOTP step accepted per user, in memory (a restart reopens at
        # most the 90 s window); a column if that ever matters.
        self._used: dict[int, int] = {}

    def enroll(self, user: User) -> TotpEnrollment:
        """A new secret, sealed on the user (enabled once a first code is accepted)."""
        secret = generate_totp_secret()
        sealed = self.box.seal(Purpose.TOTP, secret, f"user:{user.id}")
        user.totp_ciphertext, user.totp_nonce = sealed.ciphertext, sealed.nonce
        return TotpEnrollment(secret, provisioning_uri(secret, user.username))

    def accept(self, user: User, code: str) -> bool:
        """A valid code not used before (replay of an observed code refused)."""
        step = totp_step(self._secret(user), code, self.clock.now())
        if step is None or step <= self._used.get(user.id, -1):
            return False
        self._used[user.id] = step
        return True

    def check(self, user: User, code: str) -> bool:
        """A TOTP code, or a recovery code (then used up)."""
        if self.accept(user, code):
            return True
        index = match_recovery_code(code, user.recovery_codes)
        if index is None:
            return False
        user.recovery_codes = [h for i, h in enumerate(user.recovery_codes) if i != index]
        return True

    def _secret(self, user: User) -> str:
        if user.totp_ciphertext is None or user.totp_nonce is None:
            raise HivoraError("TOTP not configured")
        return self.box.open(
            Purpose.TOTP, Sealed(user.totp_nonce, user.totp_ciphertext), f"user:{user.id}"
        )


def clear_totp(user: User) -> None:
    user.totp_enabled = False
    user.totp_ciphertext = user.totp_nonce = None
    user.recovery_codes = []
