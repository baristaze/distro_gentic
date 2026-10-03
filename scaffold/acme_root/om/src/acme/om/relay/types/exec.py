"""An `exec` item as the relay keeps it: one operation of a tool call into a
customer's wall, the state its host moves it through, and how it ended.
What it runs and what it printed are the session's content, sealed under
the session's key; what recovery decides by stays in the clear."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from acme.infra.transports import FileEntry, SecretUse
from acme.infra.workspaces import IsolationSpec
from acme.om.base import Created, FrozenMapping, Identifiable, Platform, Trackable
from acme.om.placement.types.work import ExecEffect, ExecOperation

Stream = Literal["stdout", "stderr"]


class ExecState(StrEnum):
    QUEUED = "queued"  # sent, and no host holds it
    RUNNING = "running"  # a host holds it under a lease
    DONE = "done"  # its host pushed how it ended
    # It ended with its outcome unknown, or never ran: its lease ran out while
    # it was unsafe, it was stopped before a host took it, or the run that sent
    # it lost the session first.
    INTERRUPTED = "interrupted"


class StopKind(StrEnum):
    """What the control stream tells a host about one item it holds. Each
    ends the command at once."""

    CANCEL = "cancel"  # the run that sent it stopped waiting for it
    INTERRUPT = "interrupt"  # a principal interrupted it
    DEADLINE = "deadline"  # its deadline passed by the platform's clock
    REVOKE = "revoke"  # its lease is no longer the host's: what it pushes is refused


class RunRequest(Platform):
    operation: Literal[ExecOperation.RUN] = ExecOperation.RUN
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    secrets: tuple[SecretUse, ...] = ()  # by name; a host resolves them inside its wall
    max_output: int = Field(default=1_000_000, gt=0)


class ReadRequest(Platform):
    operation: Literal[ExecOperation.READ_FILE] = ExecOperation.READ_FILE
    path: str
    max_bytes: int = Field(gt=0)


class WriteRequest(Platform):
    operation: Literal[ExecOperation.WRITE_FILE] = ExecOperation.WRITE_FILE
    path: str
    data: str  # base64


class ListRequest(Platform):
    operation: Literal[ExecOperation.LIST_FILES] = ExecOperation.LIST_FILES
    path: str
    limit: int = Field(gt=0)


ExecRequest = Annotated[
    RunRequest | ReadRequest | WriteRequest | ListRequest, Field(discriminator="operation")
]
"""What one item does: the session's content, sealed at rest, opened for the
host that holds the item and for nobody else."""

REQUESTS: TypeAdapter[ExecRequest] = TypeAdapter(ExecRequest)
"""Reads and writes an `ExecRequest` whole, as it is sealed and opened."""


class ExecCall(Platform):
    """What the runner's transport sends for one operation of a call."""

    session_id: UUID
    key: UUID  # the tool request's idempotency key
    request: ExecRequest
    effect: ExecEffect
    deadline: datetime
    epoch: int | None = Field(ge=0)  # the run's writer epoch; a read carries none
    spec: IsolationSpec
    # A command a person runs by hand, never an agent's: its host's owner
    # may refuse every such command (`people_commands`).
    by_person: bool = False


class ExecOutcome(Platform):
    """How an item ended, in the clear: what recovery decides by."""

    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    stopped: StopKind | None = None  # it was stopped before it ended
    # The code and the status its host refused it with, before or as it ran,
    # such as a stale epoch or a path outside the workspace.
    refused: str | None = Field(default=None, max_length=64)
    refused_status: int | None = None
    secrets: tuple[str, ...] = ()  # the secrets it used, by name


class ExecOutput(Platform):
    """What it printed or read, or why its host refused it: content."""

    stdout: str = ""
    stderr: str = ""
    data: str | None = None  # a file's bytes, in base64
    entries: tuple[FileEntry, ...] = ()
    detail: str = ""


class ExecResult(Platform):
    """What a host pushes once an item ends, as it crosses the wall."""

    outcome: ExecOutcome
    output: ExecOutput = ExecOutput()


class ExecItem(Identifiable, Trackable):
    """One operation of one call. Its id derives from the call's key, so the
    same call sent again meets it. Each time it goes on the queue it takes a
    row of its own (`row_id`, the `dispatch`th), whose id derives from its.
    What it seals is any bytes, so its JSON form spells them in base64."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    session_id: UUID
    key: UUID
    operation: ExecOperation
    effect: ExecEffect
    host_id: UUID  # the host that holds the session's workspace
    location: str  # where on that host
    spec: IsolationSpec
    deadline: datetime
    epoch: int | None = Field(default=None, ge=0)
    request: bytes = Field(repr=False)  # the sealed `ExecRequest`
    state: ExecState = ExecState.QUEUED
    dispatch: int = Field(default=1, ge=1)
    row_id: UUID
    # The queue row as its host's claim took it, and when that lease ends: the
    # relay settles the row for the host, which holds no database login.
    claim: FrozenMapping | None = None
    lease_expires_at: datetime | None = None
    outcome: ExecOutcome | None = None
    output: bytes | None = Field(default=None, repr=False)  # the sealed `ExecOutput`
    result_sha256: str | None = None  # the hash its result crossed with
    settled_at: datetime | None = None
    version: int = Field(default=1, ge=1)


class ExecPart(Identifiable, Created):
    """One part of an item's output, as its host streamed it, under the row
    of the dispatch that printed it. Its sealed text is any bytes, so its
    JSON form spells them in base64."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    session_id: UUID
    row_id: UUID
    seq: int = Field(ge=0)
    stream: Stream
    text: bytes | None = Field(repr=False)  # sealed; None when the session keeps nothing at rest
    sha256: str


class PartText(Platform):
    seq: int
    stream: Stream
    text: str


class ExecProgress(Platform):
    """What the runner reads of an item it waits on: its state, the parts
    after the last it read, and its result once it is done."""

    state: ExecState
    parts: tuple[PartText, ...] = ()
    outcome: ExecOutcome | None = None
    output: ExecOutput | None = None


class ExecDetail(Platform):
    """What the host that holds an item reads of it: the call, where the
    workspace is, and the operation opened."""

    item_id: UUID
    key: UUID
    org_id: UUID  # the host's own tenant, which its secret store is keyed by
    session_id: UUID
    effect: ExecEffect
    deadline: datetime
    epoch: int | None
    spec: IsolationSpec
    location: str
    request: ExecRequest


class ExecControl(Identifiable, Trackable):
    """One message of a host's control stream about an item it holds. The
    item stays the record; this is what reaches the host at once."""

    session_id: UUID
    item_id: UUID
    host_id: UUID
    kind: StopKind


class WorkspaceBinding(Identifiable, Trackable):
    """The host that holds a session's workspace, and where on it. A
    workspace lives where it was prepared, so every item of the session goes
    to that host."""

    session_id: UUID
    host_id: UUID
    host_name: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=1024)
    version: int = Field(default=1, ge=1)


class PrepareAnswer(Platform):
    """A host's answer to a prepare it claimed: where on it the workspace
    it made is, or why it made none. Exactly one of the two."""

    location: str | None = Field(default=None, min_length=1, max_length=1024)
    refused: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _one_of_the_two(self) -> PrepareAnswer:
        if (self.location is None) == (self.refused is None):
            raise ValueError("a prepare is answered with its location or its refusal")
        return self
