"""Pure rules of the relay: the ids an item and its queue rows take from the
call's key, what a repeat of an item may do, what an item asks of its host,
which writer epoch is stale, and how a settled item reads. Values in, values
out; no clock, no storage, no settings."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from acme.infra.workspaces import EgressMode, IsolationMode, IsolationSpec
from acme.om.base import derived_id, thaw_mapping
from acme.om.placement.types.work import ExecEffect, HostIsolation
from acme.om.relay.types.exec import ExecItem, ExecState
from acme.om.work.types.work_item import WorkItem

UNSAFE: ExecEffect = "unsafe"

CONTROL_KIND = "relay.exec_control.created"
"""The kind of the outbox row a control message lands with: the push of it
wakes the control stream of the host it is for, wherever that stream is
held open."""

REPEATABLE_ATTEMPTS = 3
"""The claims a repeatable item's queue row may spend: a lost lease puts it
back on its host's lane, and the third loss fails it."""

UNSAFE_ATTEMPTS = 1
"""An unsafe item's row is claimed once. When its lease runs out the queue's
own sweep fails it rather than requeue it, whatever else runs first."""

RESULT_CHARS = 16_000_000
"""The most a host's result of one item carries across the wall: the
characters of its JSON in base64."""

READ_BYTES = 8 * 1024 * 1024
"""The most of a file one relayed read carries. Its bytes ride in the
result in base64, and the result in base64 again, so a read of one byte
more than this still crosses within `RESULT_CHARS`, with room for the rest
of the result. A longer file is refused at once, never waited on."""

HOST_ISOLATION: dict[IsolationMode, HostIsolation] = {
    IsolationMode.VM: "vm",
    IsolationMode.CONTAINER: "container",
    IsolationMode.HOST: "directory",
}
"""The engine's isolation modes a host runs, as the hosts name them. The
twin and no workspace are not among them: an item at either names none,
and every host refuses it."""


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


def row_id(item_id: UUID, dispatch: int) -> UUID:
    """The queue row of an item's `dispatch`th time on the queue."""
    return derived_id(item_id, key_time(item_id), f"dispatch:{dispatch}")


def part_id(row: UUID, seq: int) -> UUID:
    """A part of the output a row's run printed, by its place in it."""
    return derived_id(row, key_time(row), f"part:{seq}")


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


def held_by(item: ExecItem, worker_id: str) -> bool:
    """Whether the item is running under the claim `worker_id` made."""
    return (
        item.state is ExecState.RUNNING
        and item.claim is not None
        and item.claim.get("claimed_by") == worker_id
    )


def claimed_row(item: ExecItem) -> WorkItem:
    """The queue row as its host's claim took it, which the relay settles
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
