"""The payloads of the work a session produces outside the cloud's
runners: what each kind must name so its item goes to the lane where its
environment is. The work queue fixes them per kind (`WORK_PAYLOADS`); the
kinds that carry what a host or a daemon runs add their fields here."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from acme.infra.workspaces import IsolationSpec
from acme.om.base import Platform

ExecEffect = Literal["read_only", "idempotent", "unsafe"]
"""What a repeat of an `exec` item may do: its tool's effect, as the engine
names it."""

HostIsolation = Literal["vm", "container", "directory"]
"""The isolation a host runs a workspace at, as the hosts name it."""


class ExecOperation(StrEnum):
    """The one thing an `exec` item does in its workspace: an operation of
    the engine's transport."""

    RUN = "run"  # a command
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_FILES = "list_files"


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


class WorkspacePayload(Platform):
    """A workspace to prepare, release, or purge. Preparing goes to the lane
    of the session's placement, since any host of the pool may make it;
    releasing and purging go to the lane of the host that holds it, since
    a workspace lives where it was prepared.

    The work's target is the session. A prepare names the spec it is held
    to and, after it, what it asks of its host, which the host holds to its
    owner's ceilings before anything is made, as an `exec` item's does; a
    field left None asks the most."""

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

    @model_validator(mode="after")
    def _names_where_it_runs(self) -> WorkspacePayload:
        preparing = self.operation is WorkspaceOperation.PREPARE
        if preparing != (self.pool_id is not None) or preparing == (self.host_id is not None):
            raise ValueError("a prepare names its pool alone, and a release or a purge its host")
        return self


class StationPayload(Platform):
    """Work on a station, for the daemon of the lab that serves it. Its item
    goes to that lab's lane."""

    lab_id: UUID
