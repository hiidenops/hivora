"""Masks secret values in any text leaving the runner (logs, progress, errors)."""

from collections.abc import Iterable

MASK = "••••••"


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Longest first so a secret containing another one is fully masked.
        self._secrets = sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text
