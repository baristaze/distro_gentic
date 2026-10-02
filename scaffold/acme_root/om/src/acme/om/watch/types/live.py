"""The live read: the short-lived, scoped handle a viewer reads one
session's open streams with, the place it resumes from, and what it reads.
A stream is the parts of one step, numbered from 0, as the engine emits
them; the step it adds up to is the record, and a part only a cache."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform
from acme.om.steps.types.stream import StreamPart

MAX_SEEN = 64
"""The most streams one read names the last part of."""


class LiveRead(Platform):
    """A handle to one session's live streams until `expires_at`, handed to
    a viewer the way a browser app is handed a presigned URL. Whoever holds
    `handle` reads that session's open streams and nothing else, by the
    handle alone, until it expires."""

    session_id: UUID
    handle: str
    expires_at: datetime


class Grant(Platform):
    """What a handle grants once its signature verifies: one session of one
    tenant, read by one viewer, until a time."""

    org_id: UUID
    session_id: UUID
    viewer_id: UUID
    expires_at: datetime


class Seen(Platform):
    """The last part of one stream a reader saw: it resumes after it."""

    step_id: UUID
    n: int = Field(ge=0)


class LiveStream(Platform):
    """One open stream as a reader gets it: the step it adds up to, the
    oldest part the buffer still holds, and the parts after the reader's
    last. `dropped` says the buffer let go of parts the reader never saw;
    the step holds them once it is stored."""

    step_id: UUID
    first: int = Field(ge=0)
    parts: tuple[StreamPart, ...] = ()
    dropped: bool = False


class LivePage(Platform):
    """One read of a session's open streams."""

    session_id: UUID
    streams: tuple[LiveStream, ...] = ()
