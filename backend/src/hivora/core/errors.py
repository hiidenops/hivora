"""Domain errors, mapped to HTTP responses at the API layer."""


class HivoraError(Exception):
    """Base error. ``code`` is a stable, translatable identifier for the frontend."""

    code = "internal_error"

    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.details = details


class NotFoundError(HivoraError):
    code = "not_found"


class ConflictError(HivoraError):
    code = "conflict"


class ValidationError(HivoraError):
    code = "validation_error"


class PermissionDeniedError(HivoraError):
    code = "permission_denied"
