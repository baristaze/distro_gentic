"""The live read: the short-lived, scoped handle a viewer reads one
session's open streams with, the place it resumes from, and what it reads.
A stream is the parts of one step, numbered from 0, as the engine emits
them; the step it adds up to is the record, and a part only a cache. A
product's stream is read the same way, by a handle to one item's streams of
one kind, which a claimant of the kind's writer appends to while it holds
the item."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform
from acme.om.retention.crossing import Crossing
from acme.om.steps.types.stream import StreamPart

MAX_SEEN = 64
"""The most streams one read names the last part of."""

MAX_ENTRY = 10**14 - 2
"""The highest number an entry of a product's stream takes. The shared
cache's script spells an entry's id `0-<n + 1>`, and spells a number at or
past 10^14 in exponent form, which is no id: such an entry would land
nothing, and a read after it would read nothing."""


class LiveRead(Platform):
    """A handle to one session's live streams until `expires_at`, handed to
    a viewer the way a browser app is handed a presigned URL. Whoever holds
    `handle` reads that session's open streams and nothing else, by the
    handle alone, until it expires."""

    session_id: UUID
    handle: str
    expires_at: datetime


class Grant(Platform):
    """What a handle grants once its signature verifies: one session, read
    by one viewer, until a time. A session's id is the platform's, never
    two tenants', so the session names its tenant."""

    session_id: UUID
    viewer_id: UUID
    expires_at: datetime


class Seen(Platform):
    """The place of the last part of one stream a reader saw, the `last` of
    a part that joins several: it resumes after it."""

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


class Entry(Platform):
    """One numbered entry of a product's stream, its bytes the claimant's."""

    n: int = Field(ge=0, le=MAX_ENTRY)
    data: bytes


class SentEntry(Entry):
    """An entry as a claimant sends it across the wall: its number, its
    bytes, and the crossing it declared of them, which the bytes match
    before anything reads them."""

    crossing: Crossing


class Appended(Platform):
    """What a claimant appends to one stream of its kind for the item it
    holds, under the claim token its claim was handed: the stream, and its
    entries in their order. An entry numbered at or below the stream's last
    lands nothing."""

    claim_token: UUID
    stream: UUID
    entries: tuple[SentEntry, ...]


class ItemRead(Platform):
    """A handle to one item's streams of one kind until `expires_at`, handed
    to a viewer as a session's is: whoever holds `handle` reads those
    streams and nothing else, by the handle alone, until it expires."""

    item_id: UUID
    kind: str
    handle: str
    expires_at: datetime


class ItemGrant(Platform):
    """What an item's handle grants once its signature verifies: one item's
    streams of one kind, read by one viewer, until a time. An item's id is
    the platform's, never two tenants', so the item names its tenant."""

    item_id: UUID
    kind: str
    viewer_id: UUID
    expires_at: datetime


class ItemSeen(Platform):
    """The number of the last entry of one stream a reader saw: it resumes
    after it."""

    stream: UUID
    n: int = Field(ge=0, le=MAX_ENTRY)


class ItemStream(Platform):
    """One open stream of an item as a reader gets it: the oldest entry the
    buffer still holds, the entries after the reader's last, and whether the
    buffer let go of entries the reader never saw."""

    stream: UUID
    first: int = Field(ge=0)
    entries: tuple[Entry, ...] = ()
    dropped: bool = False


class ItemPage(Platform):
    """One read of an item's open streams of one kind."""

    item_id: UUID
    kind: str
    streams: tuple[ItemStream, ...] = ()
