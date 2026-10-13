"""A zone's start order, from the dependencies between its apps: pure, no I/O.

A dependency ``(app, needs)`` reads "app starts after needs" (and stops before it). The order
is a list of steps: each holds the apps whose dependencies are all in the steps before, so
the apps of a step can start together. A loop has no order: it is refused, and named.
"""

from collections import defaultdict
from collections.abc import Iterable

from hivora.core.errors import ConflictError, ValidationError

Dependency = tuple[int, int]  # (app, the app it starts after)


class SelfDependencyError(ValidationError):
    code = "invalid_dependency"


class DependencyOutsideZoneError(ConflictError):
    code = "dependency_outside_zone"


class DependencyCycleError(ConflictError):
    code = "dependency_cycle"


def check(apps: Iterable[int], dependencies: Iterable[Dependency]) -> list[Dependency]:
    """The dependencies of a zone's apps, valid: sorted, without duplicates. Refused: an app
    after itself, an app of another zone (or unknown), a loop."""
    members = set(apps)
    found: set[Dependency] = set()
    for app, needs in dependencies:
        if app == needs:
            raise SelfDependencyError("an app cannot start after itself", app=app)
        if app not in members or needs not in members:
            outside = app if app not in members else needs
            raise DependencyOutsideZoneError("both apps must be in the zone", app=outside)
        found.add((app, needs))
    valid = sorted(found)
    steps(members, valid)  # refuses a loop
    return valid


def steps(apps: Iterable[int], dependencies: Iterable[Dependency]) -> list[list[int]]:
    """The apps in start order, step by step (each step sorted); a loop is refused."""
    members = set(apps)
    needs: dict[int, set[int]] = {a: set() for a in members}
    for app, need in dependencies:
        if app in members and need in members:
            needs[app].add(need)
    order: list[list[int]] = []
    placed: set[int] = set()
    while len(placed) < len(members):
        step = sorted(a for a in members - placed if needs[a] <= placed)
        if not step:
            loop = _loop({a: needs[a] - placed for a in members - placed})
            raise DependencyCycleError("these apps wait for each other", apps=loop)
        order.append(step)
        placed.update(step)
    return order


def blocked(failed: Iterable[int], dependencies: Iterable[Dependency]) -> set[int]:
    """The apps that cannot start because one they need (even through others) failed."""
    dependents: dict[int, set[int]] = defaultdict(set)
    for app, need in dependencies:
        dependents[need].add(app)
    out: set[int] = set()
    todo = list(failed)
    while todo:
        for app in dependents[todo.pop()]:
            if app not in out:
                out.add(app)
                todo.append(app)
    return out - set(failed)


def _loop(needs: dict[int, set[int]]) -> list[int]:
    """One loop among apps that all wait (each has a need left): followed from the smallest
    until an app comes back; the apps of the loop, in the order met."""
    seen: list[int] = []
    app = min(needs)
    while app not in seen:
        seen.append(app)
        app = min(needs[app])
    return seen[seen.index(app) :]
