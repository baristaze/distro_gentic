"""A notification: one person told, on one channel, that a parked session
waits on them, with the link to the one action that clears the park."""

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
    """What a park asks of people: the one action that clears it, its link,
    what the notification says, and exactly who may take the action."""

    action: Stored = Field(min_length=1, max_length=MAX_NAME)
    link: Stored = Field(min_length=1, max_length=MAX_NAME)
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
    recipients: tuple[UUID, ...]


class Notification(Identifiable, Created):
    """One recipient told on one channel. Its id is derived from the park (the
    step that wrote it), the action, the recipient, and the channel, so a
    park tells each of them once. `provenance` is what served
    a post on an integration: a twin's post is named a twin's; the portal's
    is the platform's own, and names none."""

    recipient: UUID
    session_id: UUID
    park_step: UUID
    reason: ParkReason
    unlock: Stored = Field(min_length=1, max_length=MAX_NAME)
    action: Stored = Field(min_length=1, max_length=MAX_NAME)
    link: Stored = Field(min_length=1, max_length=MAX_NAME)
    channel: Stored = Field(min_length=1, max_length=MAX_NAME)
    address: Stored = Field(default="", max_length=MAX_NAME)
    provenance: Provenance | None = None
    text: Stored = Field(min_length=1, max_length=MAX_TEXT)
