"""An `exec` item as the relay keeps it: one operation of a tool call into a
customer's wall, the state its host moves it through, and how it ended.
What it runs and what it printed are the session's content, sealed under
the session's key; what recovery decides by stays in the clear. No file
and no output rides in it or in its result: each crosses as an object in
the store, sealed under a key of its own, and the item carries the
object's reference, its size, its digest, and that key."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from acme.infra.agent_workspaces import IsolationSpec
from acme.infra.transports import FileEntry, SecretUse
from acme.om.agent_workspaces.types.snapshot import DIGEST, REFERENCE
from acme.om.base import FrozenMapping, Identifiable, OmBase, Trackable
from acme.om.placement.types.work import ExecEffect, ExecOperation
from acme.om.retention.crossing import Crossing

Stream = Literal["stdout", "stderr"]

ObjectKind = Literal["output", "file"]
"""The objects an item moves: its `output`, what it printed or listed, and
a read's or a write's `file`."""

OUTPUT_CHARS = 1_000_000
"""The most characters of each stream a relayed command keeps: the engine's
own default. Past them its head and its tail are kept."""

DETAIL_CHARS = 1000
"""The most characters of why a host refused an item, or what it says of how
it ended, that a result carries."""

SECRETS = 32
"""The most secrets one relayed command uses, so a result that names them
stays small."""


def _from_the_start(offset: int) -> bool:
    """An offset of 0, which the wire leaves out."""
    return offset == 0


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


class RunRequest(OmBase):
    operation: Literal[ExecOperation.RUN] = ExecOperation.RUN
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    # By name; a host resolves them inside its wall.
    secrets: tuple[SecretUse, ...] = Field(default=(), max_length=SECRETS)
    max_output: int = Field(default=OUTPUT_CHARS, gt=0, le=OUTPUT_CHARS)


class ObjectRef(OmBase):
    """A file a write hands its host, as the object that holds it: where it
    is under the tenant, the size and the digest of the file, and the key it
    is sealed under (base64), which opens this object and no other."""

    reference: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    digest: str = Field(pattern=DIGEST)
    key: str = Field(min_length=1, max_length=64)


class ObjectSlot(OmBase):
    """An object an item's host uploads: where it is under the tenant, the
    key it seals it under (base64), and the store's multipart upload of
    it."""

    reference: str = Field(min_length=1, max_length=512)
    key: str = Field(min_length=1, max_length=64)
    upload_id: str = Field(min_length=1, max_length=1024)


class StoredObject(OmBase):
    """What a host declares of an object it uploaded: the size and the
    digest of what it sealed, which what the object opens to must match."""

    size: int = Field(ge=0)
    digest: str = Field(pattern=DIGEST)


class ReadRequest(OmBase):
    operation: Literal[ExecOperation.READ_FILE] = ExecOperation.READ_FILE
    path: str
    max_bytes: int = Field(gt=0)
    # Written only past the start, so a read from the start is the item a
    # release before it wrote, which its API and its hosts still take.
    offset: int = Field(default=0, ge=0, exclude_if=_from_the_start)


class WriteRequest(OmBase):
    """A whole file written; its bytes cross as the item's `file_in`."""

    operation: Literal[ExecOperation.WRITE_FILE] = ExecOperation.WRITE_FILE
    path: str


class ListRequest(OmBase):
    operation: Literal[ExecOperation.LIST_FILES] = ExecOperation.LIST_FILES
    path: str
    limit: int = Field(gt=0)


class McpRequest(OmBase):
    """A call of a tool of an MCP server the host runs, by the name its
    owner gives the server. The host lists the server's tools, calls this
    one only when it lists it as `definition` holds it, the definition a
    person reviewed, and answers the server's text. Its credential is the
    host's own, never sent."""

    operation: Literal[ExecOperation.MCP_CALL] = ExecOperation.MCP_CALL
    server: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1)
    arguments: FrozenMapping = Field(default_factory=dict, validate_default=True)
    definition: FrozenMapping


ExecRequest = Annotated[
    RunRequest | ReadRequest | WriteRequest | ListRequest | McpRequest,
    Field(discriminator="operation"),
]
"""What one item does: the session's content, sealed at rest, opened for the
host that holds the item and for nobody else."""

REQUESTS: TypeAdapter[ExecRequest] = TypeAdapter(ExecRequest)
"""Reads and writes an `ExecRequest` whole, as an item's id derives from it."""


class ItemContent(OmBase):
    """What an item seals under the session's key: the operation, and each
    object it moves with the key that object is sealed under, so revoking
    the session's key leaves every one of them noise. A command, a call of
    a server's tool, and a listing have an `output`; a write hands its host
    a `file_in`, and a read's host uploads a `file_out`."""

    request: ExecRequest
    output: ObjectSlot | None = None
    file_in: ObjectRef | None = None
    file_out: ObjectSlot | None = None


class ExecCall(OmBase):
    """What the runner's transport sends for one operation of a call."""

    agent_session_id: UUID
    key: UUID  # the tool request's idempotency key
    request: ExecRequest
    effect: ExecEffect
    deadline: datetime
    epoch: int | None = Field(ge=0)  # the run's writer epoch; a read carries none
    spec: IsolationSpec
    # A command a person runs by hand, never an agent's: its host's owner
    # may refuse every such command (`people_commands`).
    by_person: bool = False


class ExecOutcome(OmBase):
    """How an item ended, in the clear: what recovery decides by."""

    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    stopped: StopKind | None = None  # it was stopped before it ended
    # The code and the status its host refused it with, before or as it ran,
    # such as a stale epoch or a path outside the workspace.
    refused: str | None = Field(default=None, max_length=64)
    refused_status: int | None = None
    # The secrets it used, by name.
    secrets: tuple[str, ...] = Field(default=(), max_length=SECRETS)


class Printed(OmBase):
    """What an item's output object holds: what it printed, or listed."""

    stdout: str = ""
    stderr: str = ""
    entries: tuple[FileEntry, ...] = ()


class ResultContent(OmBase):
    """What a result says beyond how the item ended, kept sealed under the
    session's key: why its host refused it, the offset a read was answered
    from (a host echoes the one it read from past the start), and the
    objects it uploaded."""

    detail: str = Field(default="", max_length=DETAIL_CHARS)
    offset: int = Field(default=0, ge=0, exclude_if=_from_the_start)
    output: StoredObject | None = None
    file: StoredObject | None = None


class ExecResult(ResultContent):
    """What a host pushes once an item ends, as it crosses the wall: how it
    ended, and what it says of it. What it printed and what it read are in
    the objects it names, never here."""

    outcome: ExecOutcome


class ExecOutput(OmBase):
    """What it printed or read, or why its host refused it, as the runner
    reads it: the output object opened, and the file a read uploaded, by
    its size and its digest, which the runner takes from the store."""

    stdout: str = ""
    stderr: str = ""
    file: StoredObject | None = None
    offset: int = Field(default=0, ge=0, exclude_if=_from_the_start)
    entries: tuple[FileEntry, ...] = ()
    detail: str = ""
    # False once an item that prints into an object ran and none is whole to
    # read: what it printed is unknown, never nothing.
    kept: bool = True


class ExecItem(Identifiable, Trackable):
    """One operation of one call. Its id derives from the call's key, so the
    same call sent again meets it. Each time it goes on the queue it takes a
    row of its own (`row_id`, the `dispatch`th), whose id derives from its.
    What it seals is any bytes, so its JSON form spells them in base64."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    agent_session_id: UUID
    key: UUID
    operation: ExecOperation
    effect: ExecEffect
    host_id: UUID  # the host that holds the session's workspace
    location: str  # where on that host
    spec: IsolationSpec
    deadline: datetime
    epoch: int | None = Field(default=None, ge=0)
    request: bytes = Field(repr=False)  # the sealed `ItemContent`
    state: ExecState = ExecState.QUEUED
    dispatch: int = Field(default=1, ge=1)
    row_id: UUID
    # The queue row as its host's claim took it, and when that lease ends: the
    # relay settles the row for the host, which holds no database login.
    claim: FrozenMapping | None = None
    lease_expires_at: datetime | None = None
    outcome: ExecOutcome | None = None
    output: bytes | None = Field(default=None, repr=False)  # the sealed `ResultContent`
    result_sha256: str | None = None  # the hash its result crossed with
    settled_at: datetime | None = None
    version: int = Field(default=1, ge=1)


class SentPart(OmBase):
    """One part of an item's output as its host sends it across the wall:
    its place in the output, its stream, its bytes, and the crossing it
    declared of them, which the bytes match before anything reads them."""

    seq: int = Field(ge=0)
    stream: str
    crossing: Crossing
    data: bytes = Field(repr=False)


class PartText(OmBase):
    seq: int
    stream: Stream
    text: str


PARTS: TypeAdapter[tuple[PartText, ...]] = TypeAdapter(tuple[PartText, ...])
"""The parts of one push, opened: what one entry of an item's live output
holds, sealed."""


class ExecProgress(OmBase):
    """What the runner reads of an item it waits on: its state, the parts
    after the last it read, and its result once it is done."""

    state: ExecState
    parts: tuple[PartText, ...] = ()
    outcome: ExecOutcome | None = None
    output: ExecOutput | None = None


class ExecDetail(OmBase):
    """What the host that holds an item reads of it: the call, where the
    workspace is, the operation opened, and each object it moves with the
    key that opens that object alone."""

    item_id: UUID
    key: UUID
    org_id: UUID  # the host's own tenant, which its secret store is keyed by
    agent_session_id: UUID
    effect: ExecEffect
    deadline: datetime
    epoch: int | None
    spec: IsolationSpec
    location: str
    request: ExecRequest
    output: ObjectSlot | None = None
    file_in: ObjectRef | None = None
    file_out: ObjectSlot | None = None
    # A write's `file_in`, signed for a GET of it alone, and when that ends.
    url: str | None = None
    url_expires_at: datetime | None = None


class IssuedObjectPart(OmBase):
    """One part of a read's object its host is to send, by the URL signed
    for its number and its length."""

    number: int = Field(ge=1)
    offset: int = Field(ge=0)
    size_bytes: int = Field(gt=0)
    url: str


class IssuedObjectUpload(OmBase):
    """The parts of a read's object the store does not hold yet, a window of
    them at a time, and how many are missing in all."""

    parts: tuple[IssuedObjectPart, ...]
    remaining: int = Field(ge=0)
    expires_at: datetime


class ExecControl(Identifiable, Trackable):
    """One message of a host's control stream about an item it holds. The
    item stays the record; this is what reaches the host at once."""

    agent_session_id: UUID
    item_id: UUID
    host_id: UUID
    kind: StopKind


class AgentWorkspaceBinding(Identifiable, Trackable):
    """The host that holds a session's workspace, and where on it. A
    workspace lives where it was prepared, so every item of the session goes
    to that host. An instance a run made for a session under an id of its
    own is bound the same way, and `instance_of` names that session: its
    placement routes the instance, and its agent project is what the host's
    owner holds the instance's work to. None for a session's own
    workspace."""

    agent_session_id: UUID
    host_id: UUID
    host_name: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=1024)
    instance_of: UUID | None = None
    version: int = Field(default=1, ge=1)


class PrepareAnswer(OmBase):
    """A host's answer to a prepare it claimed: where on it the workspace
    it made is, or why it made none. Exactly one of the two. A refusal is
    `lost` when the snapshot the host was asked to start it from is not in
    its store, or is altered there: the platform asks no host again, unless
    another live host kept it. It is `unbuilt` when the base the workspace
    starts from failed to build on the host, as when a setup command
    failed: its reason is kept with the work, so the run that waits says
    why."""

    location: str | None = Field(default=None, min_length=1, max_length=1024)
    refused: str | None = Field(default=None, min_length=1, max_length=2000)
    lost: bool = False
    unbuilt: bool = False

    @model_validator(mode="after")
    def _one_of_the_two(self) -> PrepareAnswer:
        if (self.location is None) == (self.refused is None):
            raise ValueError("a prepare is answered with its location or its refusal")
        if (self.lost or self.unbuilt) and self.refused is None:
            raise ValueError("only a refusal is lost or unbuilt")
        if self.lost and self.unbuilt:
            raise ValueError("a refusal is lost or unbuilt, never both")
        return self


class SnapshotAnswer(OmBase):
    """A host's answer to a snapshot it claimed: kept in its own store, under
    the reference the store knows it by, with the digest of its bytes and
    their size, never the bytes; or why it kept none. Exactly one of the
    two."""

    reference: str | None = Field(default=None, pattern=REFERENCE)
    digest: str | None = Field(default=None, pattern=DIGEST)
    size: int | None = Field(default=None, ge=0)
    refused: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _one_of_the_two(self) -> SnapshotAnswer:
        kept = (self.reference, self.digest, self.size)
        if self.refused is None and None in kept:
            raise ValueError("a kept snapshot names its reference, its digest, and its size")
        if self.refused is not None and kept != (None, None, None):
            raise ValueError("a snapshot is answered as kept or as refused")
        return self
