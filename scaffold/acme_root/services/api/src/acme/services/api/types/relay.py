"""The wire types of the relay: what a host reads of an `exec` item it
holds, what it pushes as the item runs and ends, and the messages of its
control stream. Each part and each result carries the bytes as they crossed
the wall, in base64, and the hash its sender declared of them."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from acme.om.retention.crossing import SHA256, CrossingKind
from acme.services.api.types.common import RequestBody, View


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
    """One part of an item's output, in the order the host read it."""

    seq: int = Field(ge=0)
    stream: OutputStream
    data: str = Field(max_length=90_000)  # base64 of the part's UTF-8 bytes
    crossing: CrossingBody


class ResultRequest(RequestBody):
    """How an item ended: the JSON of an exec result, in base64."""

    data: str = Field(max_length=16_000_000)
    crossing: CrossingBody


class ExecDetailView(View):
    """An item the host holds: the call, the workspace, and the operation."""

    item_id: UUID
    call_id: UUID  # the tool request's id: the call's idempotency key
    org_id: UUID  # the host's own tenant, which its secret store is keyed by
    session_id: UUID
    effect: str
    deadline: datetime
    epoch: int | None
    spec: dict[str, Any]
    location: str
    request: dict[str, Any]


class ExecLeaseView(View):
    lease_expires_at: datetime


class ControlView(View):
    """One line of a host's control stream. `wake` asks it to claim now,
    `ping` keeps the stream open, and the rest end the item named at once."""

    kind: ControlKind
    id: UUID | None = None
    item_id: UUID | None = None
