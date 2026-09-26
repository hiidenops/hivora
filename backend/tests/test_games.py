import io
import socket
import struct
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from hivora.core.errors import ValidationError
from hivora.games import a2s
from hivora.games import worlds as w
from hivora.games.engine import edit_lines, read_entries
from hivora.templates.catalog import TemplateInvalidError, parse_template
from hivora.templates.schema import GameList, GameSaves

CHALLENGE = b"\x01\x02\x03\x04"


def reply(request: bytes, players: list[str], maximum: int) -> bytes:
    """A Source server's answers: a challenge first, then the data."""
    h = a2s.HEADER
    if request.startswith(a2s.INFO):
        if not request.endswith(CHALLENGE):
            return h + b"A" + CHALLENGE
        body = b"\x11" + b"\x00".join(s.encode() for s in ("Srv", "map", "game", "Game")) + b"\x00"
        return h + b"I" + body + struct.pack("<hBBB", 0, len(players), maximum, 0)
    if request[5:9] != CHALLENGE:
        return h + b"A" + CHALLENGE
    rows = b"".join(struct.pack("<B", i) + n.encode() + b"\x00" + struct.pack("<lf", 0, 1.0)
                    for i, n in enumerate(players))  # fmt: skip
    return h + b"D" + struct.pack("<B", len(players)) + rows


@pytest.fixture
def a2s_server() -> Iterator[int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(5)

    def serve() -> None:
        try:
            for _ in range(4):  # info + challenge, players + challenge
                data, addr = sock.recvfrom(1500)
                sock.sendto(reply(data, ["Ragnar", "", "Freya"], 10), addr)
        except OSError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield sock.getsockname()[1]
    sock.close()


def test_a2s_query_players(a2s_server: int) -> None:
    # The unnamed player is still connecting: counted, not listed.
    assert a2s.query("127.0.0.1", a2s_server) == (3, 10, ["Ragnar", "Freya"])


def test_a2s_no_server() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(a2s.A2SError):
        a2s.query("127.0.0.1", port, timeout=0.3)


def test_line_lists_are_edited_in_place(tmp_path: Path) -> None:
    gl = GameList(id="admins", label="Admins", file="adminlist.txt", name_pattern=r"^\d{17}$")
    path = tmp_path / "adminlist.txt"
    path.write_text("// List admin players ID  ONE per line\n76561198000000001\n")
    edit_lines(path, "76561198000000002", add=True)
    edit_lines(path, "76561198000000002", add=True)  # no duplicate
    assert [e.name for e in read_entries(path, gl)] == ["76561198000000001", "76561198000000002"]
    edit_lines(path, "76561198000000001", add=False)
    assert path.read_text().splitlines() == [
        "// List admin players ID  ONE per line", "76561198000000002",
    ]  # fmt: skip


def test_file_worlds_are_grouped_by_name(tmp_path: Path) -> None:
    layout = GameSaves(marker="*.fwl")
    for f in ("Midgard.fwl", "Midgard.db", "Midgard.db.old", "Asgard.fwl", "Asgard.db", "x.txt"):
        (tmp_path / f).write_bytes(b"12345")
    found = w.list_worlds(tmp_path, "Midgard", layout)
    assert [(x.name, x.size, x.active) for x in found] == [("Midgard", 15, True),
                                                            ("Asgard", 10, False)]  # fmt: skip
    assert [p.name for p in w.world_paths(tmp_path, "Asgard", layout)] == ["Asgard.db",
                                                                          "Asgard.fwl"]  # fmt: skip
    assert w.delete_world(tmp_path, "Asgard", tmp_path, layout) == ["Asgard.db", "Asgard.fwl"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Midgard.db", "Midgard.db.old",
                                                          "Midgard.fwl", "x.txt"]  # fmt: skip
    with pytest.raises(w.WorldNotFoundError):
        w.existing_world(tmp_path, "x", layout)


async def test_file_worlds_download_as_a_zip(tmp_path: Path) -> None:
    layout = GameSaves(marker="*.fwl")
    (tmp_path / "Midgard.fwl").write_bytes(b"F")
    (tmp_path / "Midgard.db").write_bytes(b"D")
    data = b"".join([c async for c in w.zip_stream(w.world_paths(tmp_path, "Midgard", layout),
                                                   tmp_path)])  # fmt: skip
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["Midgard.db", "Midgard.fwl"]


def _template(game: dict[str, object]) -> str:
    return yaml.safe_dump({
        "apiVersion": "hivora/v1", "kind": "Template",
        "metadata": {"slug": "g", "name": "G", "version": "1.0.0", "category": "games"},
        "requirements": {"arch": ["amd64"]},
        "form": {"basic": [{"id": "world", "label": "w", "type": "string"}]},
        "services": {"server": {"image": "g", "tag": "1",
                                "volumes": [{"name": "data", "target": "/data"}]}},
        "game": game,
    })  # fmt: skip


@pytest.mark.parametrize(
    "game",
    [
        {"players": {"command": ["x"]}},  # a command needs its output format
        {"players": {"command": ["x"], "format": "minecraft", "a2s_port": 27015}},
        {"saves": {"active_field": "nope"}},
        {"saves": {"volume": "other"}},
        {"saves": {"path": "../etc"}},
        {"lists": [{"id": "a", "label": "a", "file": "/etc/passwd"}]},
        {"lists": [{"id": "a", "label": "a", "file": "x", "enabled_field": "nope"}]},
    ],
)
def test_game_section_is_checked(game: dict[str, object]) -> None:
    with pytest.raises(TemplateInvalidError):
        parse_template(_template(game), require_pinned=False)


def test_valid_game_section() -> None:
    t = parse_template(_template({
        "players": {"a2s_port": 2457},
        "saves": {"path": "save/worlds_local", "marker": "*.fwl", "active_field": "world"},
        "lists": [{"id": "admins", "label": "A", "file": "save/adminlist.txt"}],
    }), require_pinned=False)  # fmt: skip
    assert t.game and t.game.saves and t.game.saves.by_file


def test_steam_branches_public_first_newest_next() -> None:
    from hivora.games.steam import parse_branches

    data = {"data": {"42": {"depots": {"branches": {
        "old": {"buildid": "5", "description": "Build 41"},
        "public": {"buildid": "9"},
        "secret": {"buildid": "99", "pwdrequired": "1"},
        "beta": {"buildid": "10", "description": "Unstable"},
    }}}}}  # fmt: skip
    assert [o["value"] for o in parse_branches("42", data)] == ["public", "beta", "old"]
    assert parse_branches("42", data)[1]["label"] == "beta — Unstable"


def test_factorio_autosaves_are_listed(tmp_path: Path) -> None:
    layout = GameSaves(marker="*.zip")
    (tmp_path / "_autosave1.zip").write_bytes(b"PK")
    assert [w_.name for w_ in w.list_worlds(tmp_path, "", layout)] == ["_autosave1"]
    with pytest.raises(ValidationError):
        w.valid_world_name("../x")
