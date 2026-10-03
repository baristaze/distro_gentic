"""Wire types of a person's notifications: one park that waits on them, on
one channel, with the link to the one action that clears it."""

from datetime import datetime
from uuid import UUID

from acme.om.evidence.types.provenance import Provenance
from acme.om.steps.types.header import ParkReason
from acme.services.api.types.common import View


class NotificationView(View):
    """What waits on the caller: the session, why it parked, the one action
    that clears it, and that action's route, empty when none serves it yet.
    `read_at` is when the caller marked it read."""

    id: UUID
    created_at: datetime
    session_id: UUID
    reason: ParkReason
    unlock: str
    action: str
    link: str
    channel: str
    provenance: Provenance | None
    text: str
    read_at: datetime | None
