"""Steam A2S queries (UDP): players online on Source/Steam game servers.

https://developer.valvesoftware.com/wiki/Server_queries. Single-packet answers
only (a player list is small); challenges are handled.
"""

import asyncio
import socket

HEADER = b"\xff\xff\xff\xff"
INFO = HEADER + b"TSource Engine Query\x00"
TIMEOUT_S = 3.0


class A2SError(Exception):
    pass


def _exchange(sock: socket.socket, request: bytes, expected: int) -> bytes:
    """Send ``request``; answer a challenge (``A``) once. Returns the payload after the type."""
    sock.send(request)
    data = sock.recv(65535)
    if data[:4] == HEADER and data[4:5] == b"A":  # challenge: resend with it
        challenge = data[5:9]
        sock.send(request[:5] + challenge if request[4:5] == b"U" else request + challenge)
        data = sock.recv(65535)
    if data[:4] != HEADER or data[4] != expected:
        raise A2SError("unexpected A2S answer (split packets are not supported)")
    return data[5:]


def _cstring(buf: bytes, pos: int) -> tuple[str, int]:
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def query(host: str, port: int, timeout: float = TIMEOUT_S) -> tuple[int, int, list[str]]:
    """(players online, max players, names). Blocking: run it in a thread."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            info = _exchange(sock, INFO, ord("I"))
            pos = 1  # protocol version
            for _ in range(4):  # name, map, folder, game
                _, pos = _cstring(info, pos)
            online, maximum = info[pos + 2], info[pos + 3]  # after the app id (short)
            payload = _exchange(sock, HEADER + b"U" + HEADER, ord("D"))
    except (OSError, IndexError, ValueError) as exc:
        raise A2SError(f"no A2S answer from {host}:{port}: {exc}") from exc
    names, pos = [], 1  # first byte: player count
    for _ in range(payload[0]):
        pos += 1  # index
        name, pos = _cstring(payload, pos)
        pos += 8  # score (long) + duration (float)
        if name:  # connecting players have no name yet
            names.append(name)
    return online, maximum, names


async def query_async(host: str, port: int) -> tuple[int, int, list[str]]:
    return await asyncio.to_thread(query, host, port)
