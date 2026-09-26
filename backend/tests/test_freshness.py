from hivora.templates.freshness import Pin, newer, shape

PUBLISHED = {
    "2026.9.3-java25": "d3", "2026.9.2-java25": "d2", "2026.10.1-java21": "x",
    "2026.9.9-java8": "x", "latest": "moved", "v1.9.10": "a", "v1.9.9": "b", "v2": "c",
}  # fmt: skip


def pin(tag: str, digest: str = "d") -> Pin:
    return Pin("t", "img", tag, digest)


def test_same_variant_newer_version() -> None:
    found = newer(pin("2026.9.2-java25"), PUBLISHED)
    assert found and found.newest == "2026.9.3-java25"  # never java21 or java8


def test_up_to_date_and_moving_tags() -> None:
    assert newer(pin("2026.9.3-java25"), PUBLISHED) is None
    assert newer(pin("v1.9.10"), PUBLISHED) is None  # "v2" has another shape
    assert newer(pin("latest", "moved"), PUBLISHED) is None
    moved = newer(pin("latest", "old"), PUBLISHED)
    assert moved and moved.newest == "latest"


def test_shape_keeps_variant_numbers() -> None:
    pattern = shape("2026.9.2-java25")
    assert pattern and pattern.match("2027.1.1-java25") and not pattern.match("2027.1.1-java21")
    assert shape("latest") is None
