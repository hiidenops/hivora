"""TeamSpeak 3 ServerQuery, spoken inside the server's container (exec, never the network).

The query port stays unpublished: a fixed script pipes stdin to ``nc 127.0.0.1 10011`` in
the container. Every line comes from here, each value escaped by the ServerQuery rules, so
a value can never become a second command; the login travels on stdin, never in the
command line (Docker's events show it).
"""

import asyncio
from dataclasses import dataclass

from hivora.core.errors import ConflictError
from hivora.docker_gateway import DockerGateway

QUERY_PORT = 10011
# Passes on the session's $1 lines (stdin is never closed), the last one "quit": the server
# answers, then closes. (sed '/^quit$/q' would wait for one more line: it reads ahead.)
SCRIPT = f'head -n "$1" | nc -w 5 127.0.0.1 {QUERY_PORT}'
TIMEOUT_S = 15

_ESCAPES = {
    "\\": "\\\\",
    "/": "\\/",
    " ": "\\s",
    "|": "\\p",
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\v": "\\v",
}
_UNESCAPES = {v[1]: k for k, v in _ESCAPES.items()}


class QueryError(ConflictError):
    """The server refused a command (its ``error id`` and message), or did not answer."""

    code = "teamspeak_query_failed"


@dataclass(frozen=True, slots=True)
class Answer:
    id: int
    msg: str
    rows: list[dict[str, str]]


def escape(value: object) -> str:
    return "".join(_ESCAPES.get(c, c) for c in str(value))


def unescape(value: str) -> str:
    out, chars = [], iter(value)
    for c in chars:
        out.append(_UNESCAPES.get(next(chars, ""), "") if c == "\\" else c)
    return "".join(out)


def command(name: str, *flags: str, **params: object) -> str:
    """One command line: ``name key=value… -flag…`` (None values left out)."""
    parts = [name, *(f"{k}={escape(v)}" for k, v in params.items() if v is not None)]
    return " ".join([*parts, *flags])


def rows(line: str) -> list[dict[str, str]]:
    """``a=1 b|a=2 b=x`` -> [{"a": "1", "b": ""}, {"a": "2", "b": "x"}]."""
    out = []
    for record in line.split("|"):
        fields = {}
        for item in record.split(" "):
            if item:
                key, _, value = item.partition("=")
                fields[key] = unescape(value)
        out.append(fields)
    return out


def answers(output: str) -> list[Answer]:
    """The answers of a session, in the order of its commands (data, then ``error``)."""
    out: list[Answer] = []
    data: list[dict[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("error "):
            e = rows(line[6:])[0]
            out.append(Answer(int(e.get("id", "-1")), e.get("msg", ""), data))
            data = []
        elif "=" in line:  # skips the "TS3" greeting and the welcome line
            data = rows(line)
    return out


async def run(
    gateway: DockerGateway, container_id: str, password: str, commands: list[str]
) -> list[Answer]:
    """Log in as serveradmin on virtual server 1, run ``commands``, one answer each.

    The first refusal raises (later commands are still sent, their answers ignored)."""
    lines = [
        command("login", client_login_name="serveradmin", client_login_password=password),
        "use 1",
        *commands,
        "quit",
    ]
    async with asyncio.timeout(TIMEOUT_S):
        _, out = await gateway.exec_run(
            container_id,
            ["sh", "-c", SCRIPT, "ts3", str(len(lines))],
            stdin=("\n".join(lines) + "\n").encode(),
        )
    got = answers(out)
    if len(got) < len(lines) - 1:  # quit may go unanswered
        raise QueryError("the ServerQuery did not answer", output=out[-300:].replace(password, "•"))
    for ans in got[: len(lines) - 1]:
        if ans.id not in (0, 1281):  # 1281: an empty list
            raise QueryError(ans.msg or f"error {ans.id}", query_error=ans.id)
    return got[2 : len(lines) - 1]
