import pytest

from hivora.core.errors import ValidationError
from hivora.games.minecraft import GameCommandError, clean, parse_list, valid_name


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("There are 0 of a max of 10 players online:", (0, 10, [])),
        ("There are 2 of a max of 20 players online: Steve, Alex\n", (2, 20, ["Steve", "Alex"])),
        ("There are 1/8 players online:\nNotch", (1, 8, ["Notch"])),
        ("\x1b[0m§6There are 1 of a max of 5 players online: §aSteve", (1, 5, ["Steve"])),
    ],
)
def test_parse_list(text: str, expected: tuple[int, int, list[str]]) -> None:
    assert parse_list(text) == expected


def test_parse_list_rejects_other_answers() -> None:
    with pytest.raises(GameCommandError):
        parse_list("Unknown command")


@pytest.mark.parametrize("bad", ["ab", "a" * 17, "Steve; stop", "Steve\nop", "../x", "Stéve"])
def test_player_names_are_strict(bad: str) -> None:
    with pytest.raises(ValidationError):
        valid_name(bad)


def test_clean_strips_colours() -> None:
    assert clean("§aAdded §lSteve\x1b[0m") == "Added Steve"


async def test_versions_from_the_mojang_manifest() -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from hivora.games.minecraft import MinecraftVersions

    manifest = {
        "latest": {"release": "26.3", "snapshot": "26.4-snapshot-1"},
        "versions": [
            {"id": "26.4-snapshot-1", "type": "snapshot"},
            {"id": "26.3", "type": "release"},
            {"id": "1.21.1", "type": "release"},
            {"id": "b1.7.3", "type": "old_beta"},
        ],
    }

    async def serve(_: web.Request) -> web.Response:
        return web.json_response(manifest)

    app = web.Application()
    app.router.add_get("/m.json", serve)
    async with TestServer(app) as srv:
        versions = MinecraftVersions(str(srv.make_url("/m.json")))
        releases = [o["value"] for o in await versions.options(snapshots=False)]
        everything = [o["value"] for o in await versions.options(snapshots=True)]
    assert releases == ["LATEST", "SNAPSHOT", "26.3", "1.21.1"]
    assert everything == ["LATEST", "SNAPSHOT", "26.4-snapshot-1", "26.3", "1.21.1"]
