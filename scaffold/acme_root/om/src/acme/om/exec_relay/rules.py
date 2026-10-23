"""Pure rules of the exec relay: the ids an item and its queue rows take from the
call's key, what a repeat of an item may do, what an item asks of its host,
which writer epoch is stale, how a settled item reads, and where the object
a file item moves lives. Values in, values out; no clock, no storage, no
settings."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from acme.infra.agent_workspaces import EgressMode, IsolationMode, IsolationSpec
from acme.om.base import derived_id, thaw_mapping
from acme.om.exec_relay.types.exec import (
    DETAIL_CHARS,
    OUTPUT_CHARS,
    SECRETS,
    ExecItem,
    ExecState,
    ObjectKind,
)
from acme.om.placement.types.work import ExecEffect, HostIsolation
from acme.om.work.types.work_item import WorkItem

UNSAFE: ExecEffect = "unsafe"

CONTROL_KIND = "exec_relay.exec_control.created"
"""The kind of the outbox row a control message lands with: the push of it
wakes the control stream of the host it is for, wherever that stream is
held open."""

REPEATABLE_ATTEMPTS = 3
"""The claims a repeatable item's queue row may spend: a lost lease puts it
back on its host's lane, and the third loss fails it."""

UNSAFE_ATTEMPTS = 1
"""An unsafe item's row is claimed once. When its lease runs out the queue's
own sweep fails it rather than requeue it, whatever else runs first."""

ESCAPED_BYTES = 6
"""The most bytes one character takes in a result's JSON, sent as UTF-8: a
control character's escape."""

SECRET_NAME_CHARS = 200
"""The longest name of a secret a command uses."""

RESULT_CHARS = 4 * (2048 + ESCAPED_BYTES * (DETAIL_CHARS + SECRETS * (SECRET_NAME_CHARS + 3))) // 3
"""The most a host's result of one item carries across the wall: the
characters of its JSON in base64. A result holds how the item ended, the
names of the secrets it used, why its host refused it, the offset a read
was answered from, and the size and the digest of each object it uploaded:
what it printed and what it read cross as those objects, never in it. So
it is a few KiB, as a holder's call is (its route is one), whatever the
command printed."""

OUTPUT_BYTES = 2 * OUTPUT_CHARS * ESCAPED_BYTES + 1024 * 1024
"""The most an item's output object holds: both streams of a command at
`OUTPUT_CHARS`, as UTF-8 JSON, with room for a listing. A host whose output
is past it keeps none, and says so."""

PUSH_BYTES = 128_000
"""The most bytes of output one push of a host carries: one flush window's,
as a host gathers it, sealed once and kept as one entry of the item's live
output."""

PUSH_PARTS = 256
"""The most parts one push carries: a run of one stream's text each."""

OBJECTS = "exec_relay/"
"""Where, under its tenant, the objects the items of a session move live."""

HOST_ISOLATION: dict[IsolationMode, HostIsolation] = {
    IsolationMode.VM: "vm",
    IsolationMode.CONTAINER: "container",
    IsolationMode.HOST: "directory",
}
"""The engine's isolation modes a host runs, as the hosts name them. The
twin, an account of the host, and no workspace are not among them: an item
at any of them names none, and every host refuses it."""


def key_time(key: UUID) -> datetime:
    """The time a version 7 id was minted at, read off its first 48 bits, so
    an id derived from it is the same on every run that derives it."""
    return datetime.fromtimestamp((key.int >> 80) / 1000, UTC)


def exec_id(key: UUID, request: bytes, occurrence: int) -> UUID:
    """The item of one operation of a call: the call's key, what the
    operation does, and how many times the call did the very same before it
    in this run. A run that resumes the call does the same operations in
    the same order, so it meets the same items."""
    digest = hashlib.sha256(request).hexdigest()
    return derived_id(key, key_time(key), f"exec:{digest}:{occurrence}")


def session_objects(agent_session_id: UUID) -> str:
    """The prefix of every object a session's items move."""
    return f"{OBJECTS}{agent_session_id}/"


def item_objects(agent_session_id: UUID, item_id: UUID) -> str:
    """The prefix of every object one item moves, on each of its dispatches."""
    return f"{session_objects(agent_session_id)}{item_id}/"


def dispatch_objects(agent_session_id: UUID, item_id: UUID, dispatch: int) -> str:
    """The prefix of the objects an item moves on its `dispatch`th time on
    the queue: an item sent again moves new ones."""
    return f"{item_objects(agent_session_id, item_id)}{dispatch}/"


def object_reference(agent_session_id: UUID, item_id: UUID, dispatch: int, kind: ObjectKind) -> str:
    """An object an item moves on its `dispatch`th time on the queue, named
    by what it is, so the relay finds it to remove with nothing of the item
    opened."""
    return f"{dispatch_objects(agent_session_id, item_id, dispatch)}{kind}"


def row_id(item_id: UUID, dispatch: int) -> UUID:
    """The queue row of an item's `dispatch`th time on the queue."""
    return derived_id(item_id, key_time(item_id), f"dispatch:{dispatch}")


def repeatable(effect: ExecEffect) -> bool:
    return effect != UNSAFE


def max_attempts(effect: ExecEffect) -> int:
    return REPEATABLE_ATTEMPTS if repeatable(effect) else UNSAFE_ATTEMPTS


def stale(sent: int | None, holding: int) -> bool:
    """Whether an epoch a command carries is a lost run's: below the one that
    holds the session now. A read carries none, and is never stale."""
    return sent is not None and sent < holding


def asks(
    spec: IsolationSpec, location: str
) -> tuple[HostIsolation | None, tuple[str, ...] | None, tuple[str, ...]]:
    """What an item asks of its host's ceilings: its isolation, its egress,
    and the paths on the host its result reads. Open egress asks for every
    destination, as None. A bare directory is a path on the host, which its
    result reads; a container's or a VM's files are its own, and read no
    path of the host's."""
    isolation = HOST_ISOLATION.get(spec.mode)
    match spec.egress.mode:
        case EgressMode.NONE:
            egress: tuple[str, ...] | None = ()
        case EgressMode.ALLOWLIST:
            egress = spec.egress.hosts
        case EgressMode.OPEN:
            egress = None
    reads = (location,) if spec.mode is IsolationMode.HOST else ()
    return isolation, egress, reads


def setup_reaches(spec: IsolationSpec) -> bool:
    """Whether a prepare of `spec` may build its base on its host first, with
    a setup whose egress is open. Such a prepare asks its host's ceilings
    for open egress, so an owner who closed egress refuses it, whatever the
    workspace's own egress."""
    base = spec.base
    return base is not None and bool(base.setup) and base.egress.mode is EgressMode.OPEN


def held_by(item: ExecItem, worker_id: str) -> bool:
    """Whether the item is running under the claim `worker_id` made."""
    return (
        item.state is ExecState.RUNNING
        and item.claim is not None
        and item.claim.get("claimed_by") == worker_id
    )


def claimed_row(item: ExecItem) -> WorkItem:
    """The queue row as its host's claim took it, which the exec relay settles
    for the host."""
    assert item.claim is not None  # held_by's own rule
    return WorkItem.model_validate(thaw_mapping(item.claim))


def resent(item: ExecItem) -> bool:
    """Whether a run that sends the item's call again starts it over: only a
    repeatable item whose last run ended without ending its command, since
    a repeat cannot harm it. A done item is answered from its result, and
    an unsafe one is never run twice."""
    if not repeatable(item.effect):
        return False
    if item.state is ExecState.INTERRUPTED:
        return True
    return (
        item.state is ExecState.DONE
        and item.outcome is not None
        and (item.outcome.stopped is not None)
    )
