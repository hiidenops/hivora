"""Validation of user inputs against a template form.

Errors are reported per field with stable codes the UI translates.
"""

import re
import secrets
import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hivora.core.errors import ValidationError
from hivora.templates.expressions import render
from hivora.templates.schema import FormField, Template

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_SECRET_ALPHABET = string.ascii_letters + string.digits


class FormValidationError(ValidationError):
    code = "form_invalid"


@dataclass(frozen=True, slots=True)
class FormValues:
    values: dict[str, Any] = field(default_factory=dict)  # stored in revision inputs
    secrets: dict[str, str] = field(default_factory=dict)  # encrypted, never stored in clear


def generate_secret(length: int) -> str:
    return "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(length))


def _visible(f: FormField, values: Mapping[str, Any]) -> bool:
    return not f.show_if or all(values.get(k) == v for k, v in f.show_if.items())


def _coerce(f: FormField, raw: Any) -> Any:
    """Return the typed value or raise ValueError(code)."""
    t = f.type
    if t == "boolean":
        if not isinstance(raw, bool):
            raise ValueError("invalid_type")
        return raw
    if t in ("integer", "port"):
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ValueError("invalid_type")
        try:
            value: Any = int(raw)
        except ValueError:
            raise ValueError("invalid_type") from None
        if t == "port" and not 1 <= value <= 65535:
            raise ValueError("out_of_range")
    elif t == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise ValueError("invalid_type")
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("invalid_type") from None
    else:
        if not isinstance(raw, str):
            raise ValueError("invalid_type")
        value = raw.strip() if t != "secret" else raw
        # Secrets are written single-quoted to .env: no quote or newline possible.
        if t == "secret" and ("'" in value or "\n" in value):
            raise ValueError("invalid_character")
        checks = {"email": _EMAIL, "url": _URL, "domain": _DOMAIN}
        if t in checks and not checks[t].match(value.lower() if t == "domain" else value):
            raise ValueError("invalid_format")
        if t == "path" and not value.startswith("/"):
            raise ValueError("invalid_format")
    if f.range and not f.range[0] <= value <= f.range[1]:
        raise ValueError("out_of_range")
    if f.options is not None and value not in {o.value for o in f.options}:
        raise ValueError("invalid_choice")
    if f.pattern and not re.fullmatch(f.pattern, str(value)):
        raise ValueError("pattern")
    return value


def validate_inputs(
    template: Template, inputs: Mapping[str, Any], context: Mapping[str, Any]
) -> FormValues:
    """``context`` provides ``app``/``host`` for defaults such as ``{{ app.name }}``."""
    fields = {f.id: f for f in template.form.fields}
    errors: dict[str, str] = {k: "unknown_field" for k in inputs if k not in fields}
    values: dict[str, Any] = {}
    secret_values: dict[str, str] = {}

    # Defaults citing other fields ("http://{{ host.lan_ip }}:{{ form.web_port }}") come last.
    def cites_form(f: FormField) -> bool:
        return isinstance(f.default, str) and "form." in f.default

    for f in sorted(template.form.fields, key=cites_form):
        raw = inputs.get(f.id)
        if raw is None or raw == "":
            if f.type == "secret" and f.generate:
                secret_values[f.id] = generate_secret(f.generate.length)
                continue
            ctx = {**context, "form": values} if cites_form(f) else context
            raw = render(f.default, ctx) if isinstance(f.default, str) else f.default
        if raw is None or raw == "":
            if f.required and _visible(f, values):
                errors[f.id] = "required"
            continue
        try:
            value = _coerce(f, raw)
        except ValueError as exc:
            errors[f.id] = str(exc)
            continue
        if f.type == "boolean" and f.required and value is not True and _visible(f, values):
            errors[f.id] = "must_accept"
        if f.type == "secret":
            secret_values[f.id] = value
        else:
            values[f.id] = value

    if errors:
        raise FormValidationError("invalid form inputs", fields=errors)
    return FormValues(values, secret_values)
