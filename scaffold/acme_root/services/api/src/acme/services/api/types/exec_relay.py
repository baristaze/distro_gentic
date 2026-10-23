"""The wire types of the exec relay: what a host reads of an `exec` item it
holds, what it pushes as the item runs and ends, and the messages of its
control stream. Each part and each result carries the bytes as they crossed
the wall, in base64, and the hash its sender declared of them. No file and
no output rides here: each crosses as an object in the store, by URLs
signed for it alone, and a host is handed the key that opens it."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.agent_workspaces.types.snapshot import DIGEST, REFERENCE
from acme.om.exec_relay.rules import PUSH_BYTES, PUSH_PARTS, RESULT_CHARS
from acme.om.retention.crossing import SHA256, CrossingKind
from acme.services.api.types.common import RequestBody, View

PUSH_CHARS = -(-PUSH_BYTES // 3) * 4
"""The base64 of a push's bytes, the most one part of it may carry."""


def spelled_bytes(data: str) -> int:
    """The bytes base64 text spells, read off its length before it is
    decoded."""
    return len(data) * 3 // 4 - (len(data) - len(data.rstrip("=")))


class ControlKind(StrEnum):
    """What one line of a host's control stream says."""

    WAKE = "wake"  # work reached the host's lanes: claim now
    PING = "ping"  # nothing happened; the stream is open
    CANCEL = "cancel"  # end the item now: the run that sent it stopped waiting
    INTERRUPT = "interrupt"  # end the item now: a principal interrupted it
    DEADLINE = "deadline"  # end the item now: its deadline passed
    REVOKE = "revoke"  # end the item now and push nothing: its lease is gone


class OutputStream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"


class CrossingBody(RequestBody):
    """What the sender declares of the bytes it sends: what they are, their
    SHA-256 in hex, and their size."""

    kind: CrossingKind
    sha256: str = Field(pattern=SHA256)
    size: int = Field(ge=0)


class PartRequest(RequestBody):
    """One part of an item's output: its place in it, and its stream. A host
    whose pushes hold one part each sends it alone, as a push of that part,
    and it lands as one while the floor of `exec` work takes that host."""

    seq: int = Field(ge=0)
    stream: OutputStream
    data: str = Field(max_length=PUSH_CHARS)  # base64 of the part's UTF-8 bytes
    crossing: CrossingBody


class PartsRequest(RequestBody):
    """The parts of an item's output one flush window gathered, in the order
    the host read them: one push, held to its bytes before any is decoded."""

    parts: list[PartRequest] = Field(min_length=1, max_length=PUSH_PARTS)

    @model_validator(mode="after")
    def _within_a_pushs_bytes(self) -> Self:
        if sum(spelled_bytes(part.data) for part in self.parts) > PUSH_BYTES:
            raise ValueError(f"a push carries at most {PUSH_BYTES} bytes")
        return self


class ResultRequest(RequestBody):
    """How an item ended: the JSON of an exec result, in base64. It names
    the objects its host uploaded, by their size and their digest, and
    holds none of their bytes, so it is a few KiB."""

    data: str = Field(max_length=RESULT_CHARS)
    crossing: CrossingBody


class UploadRequest(RequestBody):
    """An object of an item the host uploads, and the bytes it seals: the
    item's `output`, what it printed or listed, or a read's `file`."""

    object: Literal["output", "file"]
    size_bytes: int = Field(ge=0)


class PrepareRequest(RequestBody):
    """A host's answer to a prepare it claimed: where on it the workspace it
    made is, or why it made none. Exactly one of the two. A refusal is
    `lost` when the snapshot the host was asked to start it from is not in
    its store, or is altered there, and `unbuilt` when the base the
    workspace starts from failed to build on the host."""

    location: str | None = Field(default=None, min_length=1, max_length=1024)
    refused: str | None = Field(default=None, min_length=1, max_length=2000)
    lost: bool = False
    unbuilt: bool = False


class SnapshotRequest(RequestBody):
    """A host's answer to a snapshot it claimed: kept in its own store, under
    the reference the store knows it by, with the SHA-256 of its bytes and
    their size, never the bytes; or why it kept none. Exactly one of the
    two."""

    reference: str | None = Field(default=None, pattern=REFERENCE)
    digest: str | None = Field(default=None, pattern=DIGEST)
    size: int | None = Field(default=None, ge=0)
    refused: str | None = Field(default=None, min_length=1, max_length=2000)


class PreparedView(View):
    """Whether the session's workspace is now the one this host made. When
    it is not, another host of the pool holds it, and this host lets its
    own go."""

    held: bool


class ObjectRefView(View):
    """A file a write hands its host: the object that holds it under the
    tenant, the size and the digest of the file, and the key (base64) it
    is sealed under, which opens this object alone."""

    reference: str
    size: int
    digest: str
    key: str


class ObjectSlotView(View):
    """An object the host uploads: where it is under the tenant, and the key
    (base64) it seals it under."""

    reference: str
    key: str


class ExecDetailView(View):
    """An item the host holds: the call, the workspace, the operation, and
    the objects it moves. A write's `file_in` comes by `url`, signed for a
    GET of it alone until `url_expires_at`; an `output` and a read's
    `file_out` go by the parts `POST .../upload` signs."""

    item_id: UUID
    call_id: UUID  # the tool request's id: the call's idempotency key
    org_id: UUID  # the host's own tenant, which its secret store is keyed by
    agent_session_id: UUID
    effect: str
    deadline: datetime
    epoch: int | None
    spec: dict[str, Any]
    location: str
    request: dict[str, Any]
    output: ObjectSlotView | None = None
    file_in: ObjectRefView | None = None
    file_out: ObjectSlotView | None = None
    url: str | None = None
    url_expires_at: datetime | None = None


class IssuedObjectPartView(View):
    """One part of an object to send, sealed: `size_bytes` bytes of the
    sealed object from `offset`, as the body of a PUT to `url`, straight to
    the store. The URL is signed for that length."""

    number: int
    offset: int
    size_bytes: int
    url: str


class IssuedObjectUploadView(View):
    """The parts of the object the store does not hold yet, at most a window
    of them, each good until `expires_at`. `remaining` counts every part
    still missing, these included: send these and ask again while it is
    above zero, then push the result. Asked again after an upload was cut
    off, it signs only the parts still missing."""

    parts: list[IssuedObjectPartView]
    remaining: int
    expires_at: datetime


class ExecLeaseView(View):
    lease_expires_at: datetime


class ControlView(View):
    """One line of a host's control stream. `wake` asks it to claim now,
    `ping` keeps the stream open, and the rest end the item named at once."""

    kind: ControlKind
    id: UUID | None = None
    item_id: UUID | None = None
