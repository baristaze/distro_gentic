"""The payloads of the work a session produces outside the cloud's
runners: what each kind must name so its item goes to the lane where its
environment is. The kinds' registry fixes them per kind (`placement.kinds`); the
kinds that carry what a host runs add their fields here."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from acme.infra.workspaces import IsolationSpec
from acme.om.base import Platform
from acme.om.workspaces.types.snapshot import HostSnapshot

ExecEffect = Literal["read_only", "idempotent", "unsafe"]
"""What a repeat of an `exec` item may do: its tool's effect, as the engine
names it."""

HostIsolation = Literal["vm", "container", "directory"]
"""The isolation a host runs a workspace at, as the hosts name it."""


class ExecOperation(StrEnum):
    """The one thing an `exec` item does in its workspace: an operation of
    the engine's transport, or a call of a server the host runs."""

    RUN = "run"  # a command
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_FILES = "list_files"
    # A call of a tool of an MCP server the host runs, beside the workspace.
    MCP_CALL = "mcp_call"


class ExecPayload(Platform):
    """`exec` work at wire version 1: one operation of a tool call, for the
    host that holds the session's workspace. Its item goes to that host's
    lane.

    It names the relay's item and what a repeat of it may do, never what it
    runs: the command, the path, and the bytes are the session's content,
    sealed under its key in the relay's record with the deadline and the
    writer epoch, and a host reads them through the gateway while it holds
    the item. The fields after `spec` are what the item asks of its host,
    which the host holds to its owner's ceilings before anything runs; a
    field left None asks the most."""

    host_id: UUID
    item_id: UUID  # the relay's item, whose id derives from the call's key
    session_id: UUID
    key: UUID  # the tool request's idempotency key
    operation: ExecOperation
    effect: ExecEffect
    spec: IsolationSpec  # the session's isolation
    isolation: HostIsolation | None
    egress: tuple[str, ...] | None  # None is open egress
    reads: tuple[str, ...]  # the paths on the host its result reads
    by_person: bool = False
    project_id: UUID | None = None


class WorkspaceOperation(StrEnum):
    PREPARE = "prepare"  # a host in the session's placement makes the workspace
    RELEASE = "release"  # the holding host lets it go
    PURGE = "purge"  # the holding host destroys it
    SNAPSHOT = "snapshot"  # the holding host keeps a snapshot of it in its own store
    ERASE = "erase"  # a host's store lets the session's snapshots go


class WorkspacePayload(Platform):
    """A workspace to prepare, release, purge, or snapshot, or a session's
    snapshots to erase. Preparing goes to the lane of the session's
    placement, since any host of the pool may make it; releasing, purging,
    and snapshotting go to the lane of the host that holds it, since a
    workspace lives where it was prepared, and erasing to the host whose
    store keeps the snapshots. A prepare that starts the workspace from a
    snapshot names it (`snapshot`: its reference, digest, and size), and
    goes to the lane of the host that holds the workspace when one does, so
    that host replaces it; a snapshot names the id it is kept under, and,
    for a fork, the child it is kept for (`kept_for`): the host takes the
    session's workspace and keeps the copy as the child's, so no erase of
    the session's snapshots reaches it.

    The work's target is the session. A prepare names the spec it is held
    to and, after it, what it asks of its host, which the host holds to its
    owner's ceilings before anything is made, as an `exec` item's does; a
    field left None asks the most. A prepare of an instance a run makes for
    a session under an id of its own targets the instance, and names the
    session in `instance_of`: the pool and the project are that session's."""

    operation: WorkspaceOperation
    pool_id: UUID | None = None
    host_id: UUID | None = None
    session_id: UUID | None = None
    spec: IsolationSpec | None = None
    isolation: HostIsolation | None = None
    egress: tuple[str, ...] | None = None  # None is open egress
    reads: tuple[str, ...] = ()
    by_person: bool = False
    project_id: UUID | None = None
    instance_of: UUID | None = None
    snapshot: HostSnapshot | None = None
    kept_for: UUID | None = None

    @model_validator(mode="after")
    def _names_where_it_runs(self) -> WorkspacePayload:
        if self.operation is WorkspaceOperation.PREPARE:
            if self.pool_id is None or (self.host_id is not None and self.snapshot is None):
                raise ValueError(
                    "a prepare names its pool, and the host that holds the workspace only "
                    "when it starts it from a snapshot"
                )
        elif self.pool_id is not None or self.host_id is None:
            raise ValueError("a release, a purge, a snapshot, or an erase names its host alone")
        named = self.snapshot
        if self.operation is WorkspaceOperation.SNAPSHOT:
            if named is None or named.reference is not None:
                raise ValueError("a snapshot names the id it is kept under, and nothing more")
        elif self.operation is WorkspaceOperation.PREPARE:
            if named is not None and None in (named.reference, named.digest, named.size):
                raise ValueError("a restore names its snapshot's reference, digest, and size")
        elif named is not None:
            raise ValueError("a release, a purge, or an erase names no snapshot")
        if self.kept_for is not None and (
            self.operation is not WorkspaceOperation.SNAPSHOT or self.kept_for == self.session_id
        ):
            raise ValueError("only a snapshot is kept for another session, and never its own")
        return self
