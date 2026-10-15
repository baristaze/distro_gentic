"""The claimant kinds, as a registry, and the platform's kinds a claimant
takes. A claimant kind names who claims through the gateway, the prefix of
the credential the platform issues it, and, read off its identity alone,
the lanes it takes work from and the kinds it takes from each. A kind a
claimant takes is a `PlacedKindSpec`: a work kind that names its claimant
kind and reads its lane off its payload. The business root registers the
platform's below the marker of `root.KINDS`, and a product's join them
(`platform_root.ProductKinds.work`); the platform's host registers here as
a product's claimant does at its roots."""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from acme.om.context import Permission
from acme.om.placement.rules import host_lane, pool_lane
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.work import ExecPayload, WorkspacePayload
from acme.om.work.kinds import WorkKinds, WorkKindSpec


class PlacementWorkKind(StrEnum):
    """The names of the platform's kinds a host claims through the gateway."""

    EXEC = "EXEC"  # a command or a file operation, for the host that holds the workspace
    WORKSPACE = "WORKSPACE"  # a workspace to prepare, release, or purge


Place = Callable[[Any], str]
"""Where an item of a kind goes, read off its payload as the kind's shape
parses it: the lane the claimants of the kind serve."""


@dataclass(frozen=True)
class PlacedKindSpec(WorkKindSpec):
    """A kind of work a claimant takes through the gateway. `place` reads the
    lane its item goes to off the payload, at every enqueue; `claimant` is the
    claimant kind that takes it, which names it back. No worker of the
    platform's own runs it."""

    place: Place | None = None
    claimant: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.claimant is None or self.place is None:
            raise ValueError(f"{self.name} is claimed through the gateway, so it names both")


def claimed_by(work: WorkKinds, claimant: str) -> frozenset[str]:
    """The kinds a claimant of that kind takes through the gateway."""
    return frozenset(
        spec.name for spec in work if isinstance(spec, PlacedKindSpec) and spec.claimant == claimant
    )


CLAIMANT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
"""A claimant kind's name: the prefix of the name its claims carry."""

CREDENTIAL_PREFIX = re.compile(r"^[a-z]{2,7}_$")
"""A claimant kind's credential prefix: a few letters and an underscore, so
no prefix starts another."""

Claims = Callable[[Claimant], tuple[tuple[str, tuple[str, ...]], ...]]
"""The lanes a claimant takes work from, in the order it takes it, and the
kinds it takes from each, all read off its identity."""

HOST = "host"
"""The platform's claimant: a workspace host, which prepares workspaces and
runs commands in them."""

HOST_PREFIX = "hst_"
"""A host credential's prefix: the gateway's tenant transitions know no
such prefix and refuse it, and the host routes refuse every other."""


@dataclass(frozen=True)
class ClaimantKindSpec:
    """Who claims through the gateway: its name, the lanes and kinds its
    identity claims, and the prefix of the credential the platform issues
    it, which names its kind. A kind it names is taken only when that kind
    names this claimant kind back (`WorkKindSpec.claimant`)."""

    name: str
    claims: Claims
    prefix: str

    def __post_init__(self) -> None:
        if not CLAIMANT_NAME.match(self.name):
            raise ValueError(f"a claimant kind is named in lower case, never {self.name!r}")
        if not CREDENTIAL_PREFIX.match(self.prefix):
            raise ValueError(
                f"claimant kind {self.name}: a credential prefix is a few lower-case "
                f"letters and an underscore, never {self.prefix!r}"
            )


class ClaimantKinds:
    """The claimant kinds a process knows, each once; a name or a credential
    prefix registered twice is refused, so a product never takes over the
    platform's host, and a credential names one kind. `reserved` are the
    prefixes of the platform's other credentials, which no claimant kind
    takes."""

    def __init__(self, specs: Iterable[ClaimantKindSpec], reserved: Iterable[str] = ()) -> None:
        taken = frozenset(reserved)
        found: dict[str, ClaimantKindSpec] = {}
        prefixes: dict[str, ClaimantKindSpec] = {}
        for spec in specs:
            if spec.name in found:
                raise ValueError(f"claimant kind {spec.name} is registered twice")
            if spec.prefix in prefixes or spec.prefix in taken:
                raise ValueError(f"claimant kind {spec.name}: prefix {spec.prefix} is taken")
            found[spec.name] = spec
            prefixes[spec.prefix] = spec
        self._specs: Mapping[str, ClaimantKindSpec] = MappingProxyType(found)
        self._prefixes: Mapping[str, ClaimantKindSpec] = MappingProxyType(prefixes)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[ClaimantKindSpec]:
        return iter(self._specs.values())

    def get(self, name: str) -> ClaimantKindSpec | None:
        return self._specs.get(name)

    def of_credential(self, credential: str) -> ClaimantKindSpec | None:
        """The kind whose prefix the credential carries; None for any other."""
        head, underscore, _ = credential.partition("_")
        return self._prefixes.get(head + underscore) if underscore else None


def held_to(claimants: ClaimantKinds, work: WorkKinds) -> None:
    """Refuses a registry where a kind names a claimant kind nobody
    registered: its work would wait in a lane no claimant serves. A
    claimant kind that names another's kind takes none of it
    (`claims_of`)."""
    for spec in work:
        if isinstance(spec, PlacedKindSpec) and spec.claimant not in claimants:
            raise ValueError(f"{spec.name} is claimed by {spec.claimant}, which is not registered")


def placed_lane(spec: WorkKindSpec | None, payload: Mapping[str, object]) -> str | None:
    """The lane where a kind with a lane of its own goes, read off its
    payload; None for a kind with none, or one this process does not know.
    The payload is the shape the kind fixes, which the enqueue holds it
    to."""
    if not isinstance(spec, PlacedKindSpec) or spec.place is None:
        return None
    return spec.place(spec.payload.model_validate(payload))


def claims_of(
    claimants: ClaimantKinds, work: WorkKinds, claimant: Claimant
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The lanes a claimant takes work from, in the order it takes it, and
    the kinds it takes from each, all read off its identity: only the kinds
    that name its kind back, so no claimant kind takes another's work. A
    claimant of a kind this process does not know takes nothing."""
    spec = claimants.get(claimant.kind)
    if spec is None:
        return ()
    own = claimed_by(work, claimant.kind)
    taken: list[tuple[str, tuple[str, ...]]] = []
    for lane, kinds in spec.claims(claimant):
        mine = tuple(kind for kind in kinds if kind in own)
        if mine:
            taken.append((lane, mine))
    return tuple(taken)


def _exec_lane(payload: ExecPayload) -> str:
    return host_lane(payload.host_id)


def _workspace_lane(payload: WorkspacePayload) -> str:
    """A prepare goes to its pool, since any host of the pool may make it,
    unless it restores a snapshot over the workspace a host holds; that,
    and a release, a purge, a snapshot, or an erase, go to the host the
    payload names."""
    if payload.host_id is None:
        assert payload.pool_id is not None  # the payload's own rule
        return pool_lane(payload.pool_id)
    return host_lane(payload.host_id)


def _host_claims(claimant: Claimant) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """A host runs what its workspaces need first, then prepares one for its
    pool."""
    return (
        (host_lane(claimant.id), (PlacementWorkKind.EXEC, PlacementWorkKind.WORKSPACE)),
        (pool_lane(claimant.pool_id), (PlacementWorkKind.WORKSPACE,)),
    )


PLACED_KINDS: tuple[WorkKindSpec, ...] = (
    # A session's run asks for these, relayed from its own commit; what each
    # runs was asked for by a call its principal's own permissions allowed.
    PlacedKindSpec(
        PlacementWorkKind.EXEC, ExecPayload, Permission.WRITE, place=_exec_lane, claimant=HOST
    ),
    PlacedKindSpec(
        PlacementWorkKind.WORKSPACE,
        WorkspacePayload,
        Permission.WRITE,
        place=_workspace_lane,
        claimant=HOST,
    ),
)
"""The platform's kinds a host claims through the gateway, each on the
lane where its environment is."""

HOST_CLAIMANT = ClaimantKindSpec(HOST, _host_claims, HOST_PREFIX)


def platform_claimant_kinds() -> ClaimantKinds:
    """The platform's own claimant kinds: the host."""
    return ClaimantKinds((HOST_CLAIMANT,))
