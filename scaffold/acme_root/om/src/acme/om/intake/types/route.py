"""What the router did with one event: the session it found, and the one
effect the routing table gives the event there."""

from enum import StrEnum
from uuid import UUID

from acme.om.base import Platform


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
    `caused_by` is the session whose own act the event is, for an
    automation to tell its own sessions' events from others'. `step_id` is
    the input the session received, when it received one."""

    event_id: UUID
    integration: str
    arrival: str
    effect: Effect
    session_id: UUID | None = None
    step_id: UUID | None = None
    principal_id: UUID | None = None  # the mapped user a principal's message speaks for
    caused_by: UUID | None = None
