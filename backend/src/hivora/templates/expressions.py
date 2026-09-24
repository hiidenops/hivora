"""The restricted ``{{ ... }}`` substitution language of ``hivora/v1`` templates.

Grammar (deliberately tiny, no logic):

    expr    := path ( "|" filter )*
    path    := namespace "." name ( "." name )*
    filter  := "lower" | "upper" | "quote" | "default" "(" literal ")"
    literal := "..." | '...' | number | true | false

Namespaces: form, secret, app, host, service. Secrets are never rendered as
values: they become ``${HV_SECRET_<KEY>:-}`` references resolved by Compose
from the app's ``.env`` file (empty when a secret is unset, e.g. an optional
API key, without a "variable is not set" warning).
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from hivora.core.errors import ValidationError

NAMESPACES = frozenset({"form", "secret", "app", "host", "service"})
FILTERS = frozenset({"default", "lower", "upper", "quote"})

# An expression never spans "}}", so "{{ a }}:{{ b }}" is two expressions.
_EXPR = re.compile(r"\{\{((?:(?!\}\}).)*)\}\}")
_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
_PATH = re.compile(rf"^{_NAME}(\.{_NAME})+$")
_FILTER = re.compile(r"^(?P<name>[a-z]+)\s*(?:\((?P<arg>.*)\))?$")


class TemplateExpressionError(ValidationError):
    code = "template_expression_invalid"


@dataclass(frozen=True, slots=True)
class Filter:
    name: str
    arg: Any = None


@dataclass(frozen=True, slots=True)
class Expression:
    source: str
    path: tuple[str, ...]
    filters: tuple[Filter, ...]

    @property
    def namespace(self) -> str:
        return self.path[0]


def secret_env_name(key: str) -> str:
    return "HV_SECRET_" + re.sub(r"[^A-Z0-9]", "_", key.upper())


def _parse_literal(raw: str, source: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise TemplateExpressionError(f"invalid literal in {source!r}") from None
    if isinstance(value, (dict, list)) or value is None:
        raise TemplateExpressionError(f"invalid literal in {source!r}")
    return value


def parse_expression(source: str) -> Expression:
    parts = [p.strip() for p in source.split("|")]
    path = parts[0]
    if not _PATH.match(path):
        raise TemplateExpressionError(f"invalid reference {path!r}")
    segments = tuple(path.split("."))
    if segments[0] not in NAMESPACES:
        raise TemplateExpressionError(f"unknown namespace {segments[0]!r} in {source!r}")
    filters = []
    for raw in parts[1:]:
        m = _FILTER.match(raw)
        if not m or m["name"] not in FILTERS:
            raise TemplateExpressionError(f"unknown filter {raw!r} in {source!r}")
        if (m["name"] == "default") != (m["arg"] is not None):
            raise TemplateExpressionError(f"bad arguments for {m['name']!r} in {source!r}")
        arg = _parse_literal(m["arg"], source) if m["arg"] is not None else None
        filters.append(Filter(m["name"], arg))
    if segments[0] == "secret" and filters:
        raise TemplateExpressionError(f"filters cannot apply to secrets: {source!r}")
    return Expression(source, segments, tuple(filters))


def find_expressions(text: str) -> list[Expression]:
    return [parse_expression(m.group(1)) for m in _EXPR.finditer(text)]


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _apply(value: Any, f: Filter) -> Any:
    if f.name == "default":
        return f.arg if value is None or value == "" else value
    text = _stringify(value)
    if f.name == "lower":
        return text.lower()
    if f.name == "upper":
        return text.upper()
    return json.dumps(text, ensure_ascii=False)  # quote


def _lookup(context: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = context
    for segment in path:
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


def evaluate(expr: Expression, context: Mapping[str, Any]) -> Any:
    if expr.namespace == "secret":
        return "${" + secret_env_name(expr.path[1]) + ":-}"
    value = _lookup(context, expr.path)
    for f in expr.filters:
        value = _apply(value, f)
    return value


def render(
    text: str, context: Mapping[str, Any], *, escape: Callable[[str], str] = lambda s: s
) -> Any:
    """Substitute every expression in ``text``.

    A string that is exactly one expression keeps the value's native type
    (e.g. an integer port); otherwise results are stringified and passed
    through ``escape`` (used to neutralize ``$`` for Compose).
    """
    whole = _EXPR.fullmatch(text.strip())
    if whole:
        expr = parse_expression(whole.group(1))
        value = evaluate(expr, context)
        return value if expr.namespace == "secret" or not isinstance(value, str) else escape(value)

    def substitute(m: re.Match[str]) -> str:
        expr = parse_expression(m.group(1))
        value = _stringify(evaluate(expr, context))
        return value if expr.namespace == "secret" else escape(value)

    return _EXPR.sub(substitute, text)
