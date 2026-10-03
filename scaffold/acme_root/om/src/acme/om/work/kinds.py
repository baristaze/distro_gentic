"""The kinds of work, as a registry. A kind is a name, the payload its items
carry, the permission that asks for it, where its items go, and the
claimant kind that takes them through the gateway. The platform's own kinds
register here, as a product's do at its roots, so no kind is a list a
product edits: each root builds the one registry its process holds from
what the product hands it (`root.PlatformPorts.kinds`), and the work
manager and placement read every kind through it."""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from acme.om.base import Platform
from acme.om.context import Permission
from acme.om.work.types.work_item import (
    DeleteAccountPayload,
    DeleteOrgPayload,
    LoopPayload,
    NoopPayload,
    OrchestrationPayload,
    ValidationPayload,
    WakeParkedPayload,
    WakeSessionPayload,
    WakeSessionsPayload,
    WorkKind,
)

KIND_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
"""A kind's name: the queue row's `kind`, and `work.<kind>` on an outbox row."""

Lane = Callable[[Any], str]
"""Where an item of a kind goes, read off its payload as the kind's shape
parses it: the lane the claimants of the kind serve."""


@dataclass(frozen=True)
class WorkKindSpec:
    """One kind of work. `payload` is the shape every item of it carries,
    which the enqueue holds it to; `permission` is what asks for it, as wide
    as its whole run, since whoever asks authorizes the run once. `lane` is
    where its items go, read off the payload; None keeps the lane an item
    came with, the platform's own. `claimant` is the claimant kind that
    takes it through the gateway; None is a worker of the platform's own,
    which claims from the queue directly."""

    name: str
    payload: type[Platform]
    permission: Permission
    lane: Lane | None = None
    claimant: str | None = None

    def __post_init__(self) -> None:
        if not KIND_NAME.match(self.name):
            raise ValueError(f"a work kind is named in capitals, never {self.name!r}")
        if self.claimant is not None and self.lane is None:
            raise ValueError(f"{self.name} is claimed through the gateway, so it names its lane")


class WorkKinds:
    """The kinds a process knows, each once. Built at a root from the
    platform's own and a product's; a name registered twice is refused, so
    a product never takes over a kind of the platform's."""

    def __init__(self, specs: Iterable[WorkKindSpec]) -> None:
        found: dict[str, WorkKindSpec] = {}
        for spec in specs:
            if spec.name in found:
                raise ValueError(f"work kind {spec.name} is registered twice")
            found[spec.name] = spec
        self._specs: Mapping[str, WorkKindSpec] = MappingProxyType(found)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[WorkKindSpec]:
        return iter(self._specs.values())

    def get(self, name: str) -> WorkKindSpec | None:
        """The kind of that name; None for one this process does not know."""
        return self._specs.get(name)

    def claimed_by(self, claimant: str) -> frozenset[str]:
        """The kinds a claimant of that kind takes through the gateway."""
        return frozenset(spec.name for spec in self if spec.claimant == claimant)

    def extended(self, specs: Iterable[WorkKindSpec]) -> WorkKinds:
        """These kinds and `specs`, each once."""
        return WorkKinds((*self, *specs))


WORK_PAYLOADS: dict[str, type[Platform]] = {
    WorkKind.NOOP: NoopPayload,
    WorkKind.ORCHESTRATION: OrchestrationPayload,
    WorkKind.WAKE_PARKED: WakeParkedPayload,
    WorkKind.DELETE_ACCOUNT: DeleteAccountPayload,
    WorkKind.DELETE_ORG: DeleteOrgPayload,
    WorkKind.WAKE_SESSION: WakeSessionPayload,
    WorkKind.WAKE_SESSIONS: WakeSessionsPayload,
    WorkKind.LOOP: LoopPayload,
    WorkKind.VALIDATION: ValidationPayload,
}
"""The payload shape of each of the work namespace's own kinds, which its
spec in `WORK_KINDS` carries."""


def _own(kind: WorkKind, permission: Permission) -> WorkKindSpec:
    return WorkKindSpec(kind, WORK_PAYLOADS[kind], permission)


WORK_KINDS: tuple[WorkKindSpec, ...] = (
    _own(WorkKind.NOOP, Permission.WRITE),
    _own(WorkKind.ORCHESTRATION, Permission.WRITE),
    _own(WorkKind.WAKE_PARKED, Permission.WRITE),
    # Only an account's deletion asks for this one, relayed from its own
    # commit: leaving is every person's right whatever their role, so no
    # route enqueues it, and the permission is the width of the handler.
    _own(WorkKind.DELETE_ACCOUNT, Permission.MANAGE_MEMBERS),
    # Only the deletion of a team org, an owner's or an operator's, asks for
    # this one, relayed from its own commit; no route enqueues it.
    _own(WorkKind.DELETE_ORG, Permission.MANAGE_MEMBERS),
    # A park asks for the first and a raised budget for the second, each
    # relayed from its own commit; the handlers append a control and project
    # the status, which WRITE covers.
    _own(WorkKind.WAKE_SESSION, Permission.WRITE),
    _own(WorkKind.WAKE_SESSIONS, Permission.WRITE),
    # A write that wakes a session asks for it, relayed from its own commit;
    # the run appends steps and projects the status, which WRITE covers, and
    # each tool call asks its principal's own permissions again. Its lane is
    # its tenant's fair share, which placement answers.
    _own(WorkKind.LOOP, Permission.WRITE),
    # A validation session's start asks for it, relayed from its own commit;
    # the run writes the session's validation and finishes the session,
    # which WRITE covers.
    _own(WorkKind.VALIDATION, Permission.WRITE),
)
"""The work namespace's own kinds, each run by a worker of the platform's.
The kinds a host claims are placement's (`placement.kinds.PLACED_KINDS`)."""
