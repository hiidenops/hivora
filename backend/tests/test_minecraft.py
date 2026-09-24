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
