"""Durable background work is a row: what to do, for which record, under
which producer key, on which lane, and its own claim. Payload shapes are
fixed per kind by the kinds' registry (`work.kinds`), as `TOPIC_PAYLOADS`
fixes them per topic; the row stores the dump."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from acme.om.base import FrozenMapping, Identifiable, Platform, Trackable
from acme.om.orchestrations.types.orchestration import ParkReason
from acme.om.steps.types.header import Park
from acme.om.steps.types.header import ParkReason as LoopParkReason


class WorkKind(StrEnum):
    """The names of the platform's own kinds. A kind is registered by its
    name (`work.kinds`), and a product's kinds are names of its own."""

    NOOP = "NOOP"  # the maintenance worker's kind: no work beyond the sweep
    ORCHESTRATION = "ORCHESTRATION"  # one step of a long-running record
    WAKE_PARKED = "WAKE_PARKED"  # the reason an org's records parked for is gone
    DELETE_ACCOUNT = "DELETE_ACCOUNT"  # a deleted account's providers, then its personal org
    DELETE_ORG = "DELETE_ORG"  # a closed team org: its providers, then the org
    MEMBER_LEFT = "MEMBER_LEFT"  # what the tenant keeps of a person who left it
    WAKE_SESSION = "WAKE_SESSION"  # a parked session's retry time has come
    WAKE_SESSIONS = "WAKE_SESSIONS"  # the reason an org's sessions parked for is gone
    LOOP = "LOOP"  # a session's loop, for the session runner to run
    # The platform's own: a validation session's check, run on a fresh
    # executor by the platform's worker, with no agent and no model call.
    VALIDATION = "VALIDATION"
    # The platform's: work a session produces where its environment is,
    # claimed by a host through the gateway.
    EXEC = "EXEC"  # a command or a file operation, for the host that holds the workspace
    WORKSPACE = "WORKSPACE"  # a workspace to prepare, release, or purge
    LEASE_NOTICE = "LEASE_NOTICE"  # a session's lease request answered, or its lease revoked


WORK_ROW_PREFIX = "work."
"""The kind of the outbox row that asks for a work item: `work.<kind>`. A write
that also starts work lands such a row beside the one that announces the entity
change, in the same statement, and the relay enqueues the item it names: the
queue is a database role of its own, so no statement reaches both."""


def work_row_kind(kind: str) -> str:
    """The outbox row kind that asks for work of this kind."""
    return WORK_ROW_PREFIX + kind


def asks_for_work(row_kind: str) -> bool:
    """Whether an outbox row asks for a work item rather than announcing a
    change; the row's kind is its destination."""
    return row_kind.startswith(WORK_ROW_PREFIX)


class WorkStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"


class WorkItem(Identifiable, Trackable):
    kind: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")  # what to do: a registered kind
    target_id: UUID  # the record it advances
    idempotency_key: UUID  # unique
    # The request that caused the work and the trace context of that request,
    # the two the run names as its cause and links its spans to. Both are the
    # item's, not the enqueue's: the relay takes them off the outbox row of
    # the write, a direct create off its caller's context, and either enqueue
    # leaves them as constructed. EMPTY_UUID is the platform's marker for no
    # principal and names a producer that knew no request; an empty
    # traceparent is a producer that ran with no tracer configured, and the
    # run then starts a trace of its own.
    request_id: UUID
    traceparent: str | None = None
    payload: FrozenMapping = Field(
        default_factory=dict, validate_default=True
    )  # the dump of the payload its kind fixes
    lane: str = (
        "default"  # routing: "default", "region:<id>", ...; a string, because lanes are dynamic
    )
    status: WorkStatus = WorkStatus.QUEUED
    available_at: datetime  # not before
    claimed_by: str | None = None
    # Minted by the claim and cleared by every hand-back: completion, release,
    # deferral, and renewal condition on it in the statement itself, so a
    # worker that holds one item twice across a requeue cannot settle the
    # first claim's copy over the second's.
    claim_token: UUID | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None


class NoopPayload(Platform):
    """The NOOP kind carries nothing."""


class MemberLeftPayload(Platform):
    """The MEMBER_LEFT kind carries nothing: its target is the user whose
    place in the tenant ended, by a member's removal or an account's
    deletion, and that id is all the work needs."""


class ValidationPayload(Platform):
    """The VALIDATION kind carries nothing: its target is the validation
    session, which holds what it runs."""


class ScheduledPayload(Platform):
    """A payload that says when its work may run. The relayed enqueue makes
    the item available at `not_before`, or at once when that has passed, so
    work that waits for a time waits in the queue and no timer holds it."""

    not_before: datetime


class OrchestrationPayload(ScheduledPayload):
    """One step of the long-running record the item targets. The step reads
    the record when it runs: its status, its cursor, and its version, which
    the step's write is conditioned on. `not_before` staggers the steps a
    sweep resumes, so a dependency that came back is not met by every parked
    record at once."""


class WakeParkedPayload(Platform):
    """The reason the org's parked records waited for is gone (a provider
    that answers again clears `provider_unavailable`); the item's target is
    the org. Every record parked for it is resumed when the item runs, or
    the one `record_id` names, when the reason was that record's alone (a
    grant, or its request's end without one, clears `resource` for the
    record it was for). A park that knows when its reason may clear (a
    provider marked out until a retry time) asks for the org's wake then:
    the item waits in the queue until `not_before`, and the parks that name
    one time land one item, so the records it wakes resume staggered."""

    reason: ParkReason
    record_id: UUID | None = None
    not_before: datetime | None = None


class WakeSessionPayload(ScheduledPayload):
    """A parked session's retry time: the item waits in the queue until
    `not_before`, the park's retry time, and the item's target is the
    session. When it runs, a session still parked on exactly `park` is
    unlocked; one that moved on is left as it is."""

    park: Park


class WakeSessionsPayload(Platform):
    """The reason the org's sessions parked for is gone (a raised budget
    clears `budget`); the item's target is the org. Every session parked for
    it is unlocked when the item runs, and its gates run again."""

    reason: LoopParkReason


class LoopPayload(Platform):
    """A session's loop to run: an input woke the session, or an unlock let
    its park go. The item's target is the session; the run reads where the
    loop is from its history, so the item carries nothing else. Each time the
    session turns pending asks for one, and a run that finds nothing to do
    writes nothing."""


class LeaseNoticePayload(Platform):
    """A lease request a session waits on was answered, by a grant or by its
    end without a lease, or the lease it was granted was revoked. The item's
    target is the session: one parked in line is unlocked, and its next run
    reads the request and tells the model. Any other session is left as it
    is: a running loop reads its requests before its next model call."""

    request_id: UUID


class DeleteAccountPayload(Platform):
    """What is left of an account once its own rows are gone: the person's
    name at the identity provider, when they signed in through it, since the
    identity that held it is gone. It is an id, never a personal field. The
    item's target is the person's personal org, which it runs in, and the org
    is deleted last."""

    provider_user_id: str | None = None


class DeleteOrgPayload(Platform):
    """What is left of a team org its owner or an operator deleted: its
    organization at the identity provider, when it had one, since the org row
    no longer names it (so no sign-in through it finds the org). It is an id.
    The item's target is the org, which it runs in, and the org is deleted
    last."""

    provider_org_id: str | None = None
