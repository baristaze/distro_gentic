"""The owner's ceilings: limits the host's owner sets in a file on the host
and the platform cannot raise. The agent projects it serves, its minimum
isolation, its egress, the paths it lets a result read, whether it
accepts people's commands, how many items it runs at once, and the MCP
servers it starts, each by the name a tenant's connector calls it. They
are read from `ceilings.toml` at startup,
held frozen, and changed by nothing the platform sends: no call answers
with them and no item carries them, so a compromised control plane still
cannot widen what the host does.

Every item a host claims is read as an ask (`ask_of`) and held to them
before anything runs. A field an item leaves out is read as the widest
ask it could make: no agent project, no isolation, open egress, a person's
command. So an item is refused unless it says what it needs and that fits.

```toml
agent_projects = ["0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"]   # or "all"
min_isolation = "container"                           # vm, container, or directory
egress = ["github.com:443", "pypi.org:443"]           # or "open"
readable = ["/srv/work"]
people_commands = false
items_at_once = 4

[mcp_servers.tracker]                                 # a server this host starts
command = "/usr/local/bin/tracker-mcp"
args = ["--read-only"]
env = { TRACKER_URL = "https://tracker.internal" }
credential = "tracker-token"                          # a secret of the host's own store
credential_env = "TRACKER_TOKEN"
```

A server is named here whole, its program, its arguments, and its
environment, so an item names a server and nothing it runs.
"""

import posixpath
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

from acme.apps.host.config import BadSetting
from acme.client.types.hosts import ClaimedWorkView, IsolationMode

STRENGTH: dict[IsolationMode, int] = {
    IsolationMode.vm: 3,
    IsolationMode.container: 2,
    IsolationMode.directory: 1,
}
"""The isolation levels by what they separate, strongest highest."""

OPEN = "open"
ALL = "all"
MOST_AT_ONCE = 64
"""The most items a host runs at once, whatever its owner writes."""
WITHIN_A_WORKSPACE = frozenset({"release", "purge", "snapshot", "erase"})
"""Workspace operations on what the host already holds: letting a workspace
go, keeping a snapshot of it in the host's own store, and letting its
snapshots go. They run no command, and nothing of the workspace leaves the
host, so only the tenant fence applies."""


SERVER_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
SERVER_KEYS = frozenset({"command", "args", "env", "cwd", "credential", "credential_env"})


@dataclass(frozen=True)
class HostServer:
    """An MCP server the owner lets this host start: its program, its
    arguments, the variables its environment holds and nothing else, and
    the credential it takes, a secret of the host's own store by name,
    placed in `credential_env`."""

    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    cwd: str | None = None
    credential: str | None = None
    credential_env: str | None = None


@dataclass(frozen=True)
class Ceilings:
    """None is the open ceiling: every agent project of the host's tenant, or any
    destination. The defaults are the closed ones."""

    agent_projects: frozenset[UUID] | None = frozenset()
    min_isolation: IsolationMode = IsolationMode.container
    egress: frozenset[str] | None = frozenset()
    readable: tuple[str, ...] = ()
    people_commands: bool = False
    items_at_once: int = 4
    mcp_servers: Mapping[str, HostServer] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Ask:
    """What one item asks of the host, read off its payload."""

    kind: str
    operation: str | None
    agent_project_id: UUID | None
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
    known = {
        "agent_projects",
        "min_isolation",
        "egress",
        "readable",
        "people_commands",
        "items_at_once",
        "mcp_servers",
    }
    unknown = set(raw) - known
    if unknown:
        raise BadSetting(f"ceilings: unknown {', '.join(sorted(unknown))}")
    agent_projects_raw = raw.get("agent_projects", [])
    egress_raw = raw.get("egress", [])
    try:
        agent_projects = (
            None
            if agent_projects_raw == ALL
            else frozenset(UUID(item) for item in _strings(agent_projects_raw, "agent_projects"))
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
    at_once = raw.get("items_at_once", Ceilings.items_at_once)
    if isinstance(at_once, bool) or not isinstance(at_once, int):
        raise BadSetting("ceilings: items_at_once is a whole number")
    if not 1 <= at_once <= MOST_AT_ONCE:
        raise BadSetting(f"ceilings: items_at_once is from 1 to {MOST_AT_ONCE}")
    return Ceilings(
        agent_projects=agent_projects,
        min_isolation=min_isolation,
        egress=egress,
        readable=tuple(posixpath.normpath(path) for path in readable),
        people_commands=people,
        items_at_once=at_once,
        mcp_servers=_servers(raw.get("mcp_servers", {})),
    )


def _servers(raw: Any) -> Mapping[str, HostServer]:
    """The MCP servers the owner names, each whole."""
    if not isinstance(raw, dict):
        raise BadSetting("ceilings: mcp_servers is a table of servers by name")
    servers: dict[str, HostServer] = {}
    for name, table in raw.items():
        where = f"ceilings: mcp_servers.{name}"
        if not SERVER_NAME.fullmatch(name) or not isinstance(table, dict):
            raise BadSetting(f"{where} is a table under a lower-case name")
        unknown = set(table) - SERVER_KEYS
        if unknown:
            raise BadSetting(f"{where}: unknown {', '.join(sorted(unknown))}")
        command = table.get("command")
        if not isinstance(command, str) or not command:
            raise BadSetting(f"{where} names its command")
        env = table.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and ENV_NAME.fullmatch(key) and isinstance(value, str)
            for key, value in env.items()
        ):
            raise BadSetting(f"{where}: env is a table of variables and their values")
        credential, variable = table.get("credential"), table.get("credential_env")
        if (credential is None) != (variable is None):
            raise BadSetting(
                f"{where} names its credential and the variable it lands in, or neither"
            )
        if credential is not None and (not isinstance(credential, str) or not credential):
            raise BadSetting(f"{where}: credential is the name of a secret of this host")
        if variable is not None and (
            not isinstance(variable, str) or not ENV_NAME.fullmatch(variable)
        ):
            raise BadSetting(f"{where}: credential_env is a variable's name")
        if variable is not None and variable in env:
            raise BadSetting(f"{where}: env names the credential's variable")
        cwd = table.get("cwd")
        if cwd is not None and (not isinstance(cwd, str) or not posixpath.isabs(cwd)):
            raise BadSetting(f"{where}: cwd is an absolute path")
        servers[name] = HostServer(
            command=command,
            args=tuple(_strings(table.get("args", []), f"mcp_servers.{name}.args")),
            env=tuple(sorted(env.items())),
            cwd=cwd,
            credential=credential,
            credential_env=variable,
        )
    return MappingProxyType(servers)


def ask_of(item: ClaimedWorkView) -> Ask:
    """The item's ask, the widest wherever it is silent or unreadable."""
    payload: Mapping[str, Any] = item.payload
    try:
        agent_project_id = (
            UUID(str(payload["agent_project_id"])) if "agent_project_id" in payload else None
        )
    except ValueError:
        agent_project_id = None
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
        agent_project_id=agent_project_id,
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


def refusals(
    ceilings: Ceilings, probed: frozenset[IsolationMode], ask: Ask, *, open_egress: bool
) -> list[str]:
    """Why the host will not run the item, one reason per ceiling it passes;
    empty when it fits. `probed` is what the host's own startup showed it
    can provide, and an item never runs at a mode outside it. `open_egress`
    is whether its startup found no cloud metadata service answering: where
    one answers, no item runs with open egress, whatever the ceilings say."""
    if ask.kind == "WORKSPACE" and ask.operation in WITHIN_A_WORKSPACE:
        return []
    found: list[str] = []
    if ceilings.agent_projects is not None and ask.agent_project_id not in ceilings.agent_projects:
        found.append("an agent project this host does not serve")
    if ask.isolation is None:
        found.append("no isolation named")
    else:
        if STRENGTH[ask.isolation] < STRENGTH[ceilings.min_isolation]:
            found.append(f"isolation {ask.isolation.value} below this host's minimum")
        if ask.isolation not in probed:
            found.append(f"isolation {ask.isolation.value} this host did not probe")
    if ceilings.egress is not None and (ask.egress is None or not ask.egress <= ceilings.egress):
        found.append("egress beyond this host's allowlist")
    if ask.egress is None and not open_egress:
        found.append("open egress on a host that reaches its cloud's metadata service")
    if not all(_readable(path, ceilings.readable) for path in ask.reads):
        found.append("a read outside this host's readable paths")
    if ask.by_person and not ceilings.people_commands:
        found.append("a person's command, which this host does not accept")
    return found
