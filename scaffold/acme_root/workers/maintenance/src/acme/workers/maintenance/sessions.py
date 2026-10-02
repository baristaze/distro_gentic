"""The handlers that wake parked agent sessions: one session whose park's
retry time came, and every session of an org whose reason to wait is gone.
And the sweep's duty that asks again for the run of a session pending with
no loop queued.

A park is "not now", never "failed": a loop that parks on a provider or a
budget resumes by itself once its unlock happens. Each handler writes the
engine's `unlock` control and leaves the session pending for a run, whose
gates run again before its next call. Both are idempotent: a session that is
no longer parked as the item says is left as it is."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.base import Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import InvalidCredential, NotFound
from acme.om.tenancy import TenancyManagerInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.handler import WorkHandlerInterface
from acme.om.work.types.work_item import (
    LoopPayload,
    WakeSessionPayload,
    WakeSessionsPayload,
    WorkItem,
    WorkKind,
)

log = logging.getLogger(__name__)


class WakeSessionHandlerImpl(WorkHandlerInterface):
    """A park's retry time came: the session the item targets is unlocked
    when it still waits on the park the item names."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.WRITE,)
    """`wake_session` writes."""

    def __init__(self, sessions: AgentSessionsManagerInterface) -> None:
        self._sessions = sessions

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        park = WakeSessionPayload.model_validate(dict(item.payload)).park
        try:
            session = await self._sessions.wake_session(ctx, item.target_id, park)
        except NotFound:
            log.info("session %s is gone; wake %s has nothing to do", item.target_id, item.id)
            return
        woken = session.status is not SessionStatus.PARKED or session.park != park
        log.info(
            "session %s in org %s at its %s retry time: %s",
            session.id,
            ctx.org_id,
            park.reason.value,
            session.status.value if woken else "still parked",
        )


class WakeSessionsHandlerImpl(WorkHandlerInterface):
    """The reason the org's sessions parked for is gone: every one of them is
    unlocked, and its gates run again when it resumes."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.WRITE,)
    """`wake_parked` writes."""

    def __init__(self, sessions: AgentSessionsManagerInterface) -> None:
        self._sessions = sessions

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        reason = WakeSessionsPayload.model_validate(dict(item.payload)).reason
        woken = await self._sessions.wake_parked(ctx, reason)
        log.info("woke %d sessions parked for %s in org %s", woken, reason.value, ctx.org_id)


class StalledOptions(Platform):
    # A session pending this long with no write is one whose loop no run
    # holds: its loop's work failed for good, or never landed. Longer than a
    # run's time, so a loop a runner holds is never asked for twice.
    stall_after: timedelta = timedelta(minutes=20)
    # How far back past `stall_after` a worker's first call reads. Every
    # call after reads on from where the one before stopped.
    lookback: timedelta = timedelta(days=1)
    batch: int = Field(default=100, gt=0)  # sessions one read takes at most


class StalledSessionsSweep:
    """The sweep's duty for a session with a pending input and no queued
    loop: it asks for the session's run again, as the person who made the
    session, as a wake does. The ask is keyed on the session's version, so
    a session asks once for each write that left it pending, however many
    passes find it. The run that takes it up asks an approval that expired
    meanwhile again, at its gate."""

    def __init__(
        self,
        sessions: AgentSessionsManagerInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        options: StalledOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessions = sessions
        self._work = work
        self._tenancy = tenancy
        self._options = options
        self._clock = clock
        # The last write the next call reads on from; None until this process
        # has read once.
        self._read_to: datetime | None = None

    async def __call__(self, rctx: RequestContext) -> int:
        """Asks for the run of each session pending with no write since
        `stall_after`; returns how many it read, so a whole batch says there
        may be more."""
        options = self._options
        before = self._clock() - options.stall_after
        after = self._read_to or before - options.lookback
        found = await self._sessions.pending_across_tenants(after, before, options.batch)
        left = [
            session.updated_at
            for org_id, session in found
            if not await self._ask(rctx, org_id, session)
        ]
        if left:
            self._read_to = min(left)
        elif len(found) >= options.batch:
            self._read_to = found[-1][1].updated_at
        else:
            self._read_to = before
        return len(found)

    async def _ask(self, rctx: RequestContext, org_id: UUID, session: AgentSession) -> bool:
        """Asks for one session's run; False when it is left for the next
        call. A deleted tenant's session goes with its tenant's purge."""
        try:
            ctx = await self._tenancy.service_context(rctx, org_id, session.created_by)
        except InvalidCredential:
            return True
        now = self._clock()
        key = derived_id(session.id, session.updated_at, f"stalled:{session.version}")
        item = WorkItem(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=session.created_by,
            updated_by=session.created_by,
            kind=WorkKind.LOOP,
            target_id=session.id,
            idempotency_key=key,
            request_id=rctx.request_id,
            payload=LoopPayload().model_dump(mode="json"),
            available_at=now,
        )
        try:
            queued = await self._work.enqueue(ctx, item)
        except Exception:
            log.exception("session %s of org %s waits for the next pass", session.id, org_id)
            return False
        if queued.id == item.id:
            log.info(
                "session %s of org %s, pending since %s with no loop, asked for its run",
                session.id,
                org_id,
                session.updated_at.isoformat(),
            )
        return True
