import ast
from pathlib import Path

import pytest

import hivora.apps.start_order as start_order
from hivora.apps.start_order import blocked, check, steps

# A zone: 1 PostgreSQL, 2 Redis, 3 Nextcloud (after 1 and 2), 4 Adminer (after 1),
# 5 nginx in front of Nextcloud (after 3), 6 a lone app.
APPS = [1, 2, 3, 4, 5, 6]
DEPS = [(3, 1), (3, 2), (4, 1), (5, 3)]


def test_the_apps_start_step_by_step_independent_ones_together() -> None:
    assert steps(APPS, DEPS) == [[1, 2, 6], [3, 4], [5]]
    assert steps(APPS, []) == [[1, 2, 3, 4, 5, 6]]  # no dependency: all at once
    assert steps([], []) == []
    # Stopping is the same order backwards: nginx first, the databases last.
    assert list(reversed(steps(APPS, DEPS))) == [[5], [3, 4], [1, 2, 6]]


def test_dependencies_are_checked_sorted_and_deduplicated() -> None:
    assert check(APPS, [(5, 3), (3, 1), (3, 2), (3, 1), (4, 1)]) == [(3, 1), (3, 2), (4, 1), (5, 3)]
    assert check(APPS, []) == []


@pytest.mark.parametrize(("deps", "error", "details"), [
    ([(3, 3)], "invalid_dependency", {"app": 3}),  # after itself
    ([(3, 9)], "dependency_outside_zone", {"app": 9}),  # an app of another zone
    ([(9, 3)], "dependency_outside_zone", {"app": 9}),
    ([(1, 3), (3, 1)], "dependency_cycle", {"apps": [1, 3]}),
    ([(1, 2), (2, 5), (5, 1), (6, 4)], "dependency_cycle", {"apps": [1, 2, 5]}),
    ([*DEPS, (1, 5)], "dependency_cycle", {"apps": [1, 5, 3]}),  # through Nextcloud
])  # fmt: skip
def test_refused_dependencies(
    deps: list[tuple[int, int]], error: str, details: dict[str, object]
) -> None:
    with pytest.raises(Exception) as caught:
        check(APPS, deps)
    assert getattr(caught.value, "code", None) == error
    assert getattr(caught.value, "details", None) == details


def test_a_failed_app_blocks_what_needs_it_not_the_other_branches() -> None:
    assert blocked({1}, DEPS) == {3, 4, 5}  # Nextcloud, Adminer, and nginx through Nextcloud
    assert blocked({2}, DEPS) == {3, 5}  # Adminer (after PostgreSQL only) still starts
    assert blocked({5}, DEPS) == set()  # nothing needs nginx
    assert blocked({1, 3}, DEPS) == {4, 5}  # the failed ones are not listed again
    assert blocked(set(), DEPS) == set()


def test_the_order_does_no_io() -> None:
    tree = ast.parse(Path(start_order.__file__).read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"collections", "collections.abc", "hivora.core.errors"}
