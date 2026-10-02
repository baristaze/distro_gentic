"""The owner's ceilings: limits the host's owner sets in a file on the host
and the platform cannot raise. The projects it serves, its minimum
isolation, its egress, the paths it lets a result read, and whether it
accepts people's commands. They are read from `ceilings.toml` at startup,
held frozen, and changed by nothing the platform sends: no call answers
with them and no item carries them, so a compromised control plane still
cannot widen what the host does.

Every item a host claims is read as an ask (`ask_of`) and held to them
before anything runs. A field an item leaves out is read as the widest
ask it could make: no project, no isolation, open egress, a person's
command. So an item is refused unless it says what it needs and that fits.

```toml
projects = ["0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"]   # or "all"
min_isolation = "container"                           # vm, container, or directory
egress = ["github.com:443", "pypi.org:443"]           # or "open"
readable = ["/srv/work"]
people_commands = false
```
"""

import posixpath
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from acme.apps.host.config import BadSetting
from acme.client.types import ClaimedWorkView, IsolationMode

STRENGTH: dict[IsolationMode, int] = {
    IsolationMode.vm: 3,
    IsolationMode.container: 2,
    IsolationMode.directory: 1,
}
"""The isolation levels by what they separate, strongest highest."""

OPEN = "open"
ALL = "all"
WITHIN_A_WORKSPACE = frozenset({"release", "purge"})
"""Workspace operations that only let go of what the host already holds:
they run nothing and read nothing, so only the tenant fence applies."""


@dataclass(frozen=True)
class Ceilings:
    """None is the open ceiling: every project of the host's tenant, or any
    destination. The defaults are the closed ones."""

    projects: frozenset[UUID] | None = frozenset()
    min_isolation: IsolationMode = IsolationMode.container
    egress: frozenset[str] | None = frozenset()
    readable: tuple[str, ...] = ()
    people_commands: bool = False


@dataclass(frozen=True)
class Ask:
    """What one item asks of the host, read off its payload."""

    kind: str
    operation: str | None
    project_id: UUID | None
    isolation: IsolationMode | None
    egress: frozenset[str] | None
    reads: tuple[str, ...]
    by_person: bool


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BadSetting(f"ceilings: {name} is a list of strings")
    return list(value)


def load(path: Path) -> Ceilings:
    """The owner's ceilings. A host with no ceilings file does not start:
    there is no default its owner did not write."""
    try:
        raw = tomllib.loads(path.read_text())
    except OSError as error:
        raise BadSetting(f"the owner's ceilings cannot be read from {path}: {error}") from None
    except tomllib.TOMLDecodeError as error:
        raise BadSetting(f"ceilings: {error}") from None
    unknown = set(raw) - {"projects", "min_isolation", "egress", "readable", "people_commands"}
    if unknown:
        raise BadSetting(f"ceilings: unknown {', '.join(sorted(unknown))}")
    projects_raw = raw.get("projects", [])
    egress_raw = raw.get("egress", [])
    try:
        projects = (
            None
            if projects_raw == ALL
            else frozenset(UUID(item) for item in _strings(projects_raw, "projects"))
        )
        min_isolation = IsolationMode(raw.get("min_isolation", IsolationMode.container.value))
    except ValueError as error:
        raise BadSetting(f"ceilings: {error}") from None
    egress = None if egress_raw == OPEN else frozenset(_strings(egress_raw, "egress"))
    readable = tuple(_strings(raw.get("readable", []), "readable"))
    if not all(posixpath.isabs(path) for path in readable):
        raise BadSetting("ceilings: every readable path is absolute")
    people = raw.get("people_commands", False)
    if not isinstance(people, bool):
        raise BadSetting("ceilings: people_commands is true or false")
    return Ceilings(
        projects=projects,
        min_isolation=min_isolation,
        egress=egress,
        readable=tuple(posixpath.normpath(path) for path in readable),
        people_commands=people,
    )


def ask_of(item: ClaimedWorkView) -> Ask:
    """The item's ask, the widest wherever it is silent or unreadable."""
    payload: Mapping[str, Any] = item.payload
    try:
        project_id = UUID(str(payload["project_id"])) if "project_id" in payload else None
    except ValueError:
        project_id = None
    try:
        isolation = IsolationMode(payload["isolation"]) if "isolation" in payload else None
    except ValueError:
        isolation = None
    egress_raw = payload.get("egress")
    egress = (
        frozenset(egress_raw)
        if isinstance(egress_raw, list) and all(isinstance(d, str) for d in egress_raw)
        else None
    )
    # An item that names no reads may read anything: an item that reads
    # nothing says so with an empty list.
    reads_raw = payload.get("reads")
    reads = (
        tuple(reads_raw)
        if isinstance(reads_raw, list) and all(isinstance(r, str) for r in reads_raw)
        else ("/",)
    )
    by_person = payload.get("by_person")
    operation = payload.get("operation")
    return Ask(
        kind=item.kind,
        operation=operation if isinstance(operation, str) else None,
        project_id=project_id,
        isolation=isolation,
        egress=egress,
        reads=reads,
        by_person=by_person is not False,
    )


def _readable(path: str, readable: tuple[str, ...]) -> bool:
    if not posixpath.isabs(path):
        return False
    normal = posixpath.normpath(path)
    return any(normal == root or normal.startswith(root.rstrip("/") + "/") for root in readable)


def refusals(ceilings: Ceilings, probed: frozenset[IsolationMode], ask: Ask) -> list[str]:
    """Why the host will not run the item, one reason per ceiling it passes;
    empty when it fits. `probed` is what the host's own startup showed it
    can provide, and an item never runs at a mode outside it."""
    if ask.kind == "WORKSPACE" and ask.operation in WITHIN_A_WORKSPACE:
        return []
    found: list[str] = []
    if ceilings.projects is not None and ask.project_id not in ceilings.projects:
        found.append("a project this host does not serve")
    if ask.isolation is None:
        found.append("no isolation named")
    else:
        if STRENGTH[ask.isolation] < STRENGTH[ceilings.min_isolation]:
            found.append(f"isolation {ask.isolation.value} below this host's minimum")
        if ask.isolation not in probed:
            found.append(f"isolation {ask.isolation.value} this host did not probe")
    if ceilings.egress is not None and (ask.egress is None or not ask.egress <= ceilings.egress):
        found.append("egress beyond this host's allowlist")
    if not all(_readable(path, ceilings.readable) for path in ask.reads):
        found.append("a read outside this host's readable paths")
    if ask.by_person and not ceilings.people_commands:
        found.append("a person's command, which this host does not accept")
    return found
