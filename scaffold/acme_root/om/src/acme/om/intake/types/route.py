"""What the router did with one event: the session it found, and the one
effect the routing table gives the event there."""

from enum import StrEnum
from uuid import UUID

from acme.om.base import Platform
from acme.om.evidence.types.provenance import Provenance


class Effect(StrEnum):
    """One row's effect, of the routing table's."""

    WAKE = "wake"  # a principal's message: wakes, and unarchives
    WAKE_AS_DATA = "wake_as_data"  # wakes, and the agent reads it as data
    WAIT = "wait"  # waits in the inbox, read at the next model call
    HAND_OVER = "hand_over"  # a person took the branch: the agent stands down
    RECORD = "record"  # for an archived session: recorded, never waking
    OWN = "own"  # the session's own act: audited, never delivered
    UNROUTED = "unrouted"  # names no session of the tenant: audited only


class Routed(Platform):
    """The router's answer for one event, as its audit entry holds it.
    `caused_by` is the session whose act through the platform's account
    the event is or follows from, as the acts it names were recorded,
    whatever session the event reaches; with no act recorded, the session
    whose own work it lands on. An automation tells its own sessions'
    events from others' by it, and a chain's hop follows it.
    `platform` is set when the platform's account wrote the event. `step_id` is
    the input the session received, when it received one. `provenance` is
    what served the event: a twin's is never taken for the real system's."""

    event_id: UUID
    integration: str
    provenance: Provenance
    arrival: str
    effect: Effect
    session_id: UUID | None = None
    step_id: UUID | None = None
    principal_id: UUID | None = None  # the mapped user a principal's message speaks for
    caused_by: UUID | None = None
    platform: bool = False
