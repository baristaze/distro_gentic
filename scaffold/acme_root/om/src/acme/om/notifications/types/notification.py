"""A notification: one person told, on one channel, that a parked session
waits on them, with the link to the one action that clears the park, when
a route of the API serves it."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from acme.om.base import Created, Identifiable, Platform
from acme.om.evidence.types.provenance import Provenance
from acme.om.steps.types.content import MAX_NAME, Stored
from acme.om.steps.types.header import ParkReason

PORTAL = "portal"
"""The channel every person has: the platform's own list of what waits on
them. Any other channel is an integration's, at an account linked to them."""

MAX_TEXT = 2_000


class Ask(Platform):
    """What a park asks of people: the one action that clears it, its link
    (empty while no route of the API serves the action), what the
    notification says, and exactly who may take the action. `posted` is
    what a post on an integration says instead, when it quotes the
    session's content, such as an agent's question: that content is sealed
    under the session's key and lives as long as its content may, so the
    row keeps `text` alone, which quotes none of it."""

    action: Stored = Field(min_length=1, max_length=MAX_NAME)
    link: Stored = Field(default="", max_length=MAX_NAME)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    posted: Stored | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    read_at: datetime | None = None
    recipients: tuple[UUID, ...]


class Notification(Identifiable, Created):
    """One recipient told on one channel. Its id is derived from the park (the
    step that wrote it), the action, the recipient, and the channel, so a
    park tells each of them once. `provenance` is what served
    a post on an integration: a twin's post is named a twin's; the portal's
    is the platform's own, and names none. `read_at` is when its recipient
    marked it read; the first mark holds."""

    recipient: UUID
    session_id: UUID
    park_step: UUID
    reason: ParkReason
    unlock: Stored = Field(min_length=1, max_length=MAX_NAME)
    action: Stored = Field(min_length=1, max_length=MAX_NAME)
    link: Stored = Field(default="", max_length=MAX_NAME)
    channel: Stored = Field(min_length=1, max_length=MAX_NAME)
    address: Stored = Field(default="", max_length=MAX_NAME)
    provenance: Provenance | None = None
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    read_at: datetime | None = None
