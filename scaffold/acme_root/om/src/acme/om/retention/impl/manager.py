import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.exceptions import InfraException, KeyRefused
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.base import EMPTY_UUID, Platform, derived_id, new_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.manager import audit_event
from acme.om.exceptions import (
    InvalidCredential,
    NotFound,
    PreconditionFailed,
    UniqueKeyTaken,
    ValidationFailed,
)
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.privacy import PrivacyManagerInterface
from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention.keys import KeyDestruction, TenantKeysInterface
from acme.om.retention.manager import RetentionManagerInterface
from acme.om.retention.projects import SessionProjectInterface
from acme.om.retention.rules import (
    content_due,
    effective,
    expiries,
    folded,
    past_bound,
    region_conflicts,
    shape_due,
)
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.types.policy import MAX_LIFETIME, TenantRetention
from acme.om.retention.types.snapshot import SessionRetention
from acme.om.steps.types.header import ControlCommand, ControlHeader
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.om.tenancy import TenancyManagerInterface

log = logging.getLogger(__name__)

CREATED = "retention.retention_policy.created"
UPDATED = "retention.retention_policy.updated"
KEY_DESTROYED = "retention.key.destroyed"
"""The audit kind of a session's key destroyed: past its content's life, by
the sweep, or before it, by the tenant's admin, whom the entry names."""
SHAPE_CANCEL = "retention.shape.cancel"
"""What a parked loop's cancel derives its id from, once per shape's life:
every pass that finds the loop still parked asks for the same cancel."""
ERASE_WRITES = 3
"""The writes an erasure makes of its snapshot at most, each after a sweep
that wrote the snapshot meanwhile."""


class RetentionOptions(Platform):
    sweep_batch: int = 100  # snapshots one read of the sweep takes up at most
    purge_batch: int = 1000  # rows one purge statement deletes at most
    # How long a session a pass could not finish waits before a pass takes
    # it up again: a loop still open, a key service that did not answer.
    retry_after: timedelta = timedelta(minutes=10)


class RetentionManagerImpl(RetentionManagerInterface):
    def __init__(
        self,
        storage: RetentionStorageInterface,
        keys: TenantKeysInterface,
        privacy: PrivacyManagerInterface,
        sessions: AgentSessionsManagerInterface,
        tenancy: TenancyManagerInterface,
        events: EventsManagerInterface,
        relay: OutboxRelayInterface,
        projects: SessionProjectInterface,
        options: RetentionOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._keys = keys
        self._privacy = privacy
        self._sessions = sessions
        self._tenancy = tenancy
        self._events = events
        self._relay = relay
        self._projects = projects
        self._options = options
        self._clock = clock

    # The tenant's policy.

    async def get_policy(self, ctx: TenantContext) -> TenantRetention:
        ctx.require(Permission.READ)
        stored = await self._storage.read_policy(ctx.org_id)
        if stored is not None:
            return stored
        now = self._clock()
        return TenantRetention(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
        )

    async def write_policy(self, ctx: TenantContext, policy: TenantRetention) -> TenantRetention:
        ctx.require(Permission.MANAGE_MEMBERS)
        if past_bound(policy.policy):
            raise ValidationFailed(f"a lifetime is at most {MAX_LIFETIME.days} days")
        for project in policy.projects:
            if past_bound(project.policy):
                raise ValidationFailed(
                    f"project {project.project_id} names a lifetime past {MAX_LIFETIME.days} days"
                )
            if region_conflicts(policy.policy, project.policy):
                raise ValidationFailed(
                    f"project {project.project_id} names a region its tenant does not"
                )
        stored = await self._storage.read_policy(ctx.org_id)
        now = self._clock()
        if stored is None:
            if policy.version != 0:
                raise PreconditionFailed("the tenant has declared no retention policy")
            created = TenantRetention(
                id=policy.id,
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                policy=policy.policy,
                projects=policy.projects,
                version=1,
            )
            rows = (versioned_row(ctx, CREATED, created.id, created.version),)
            try:
                landed = await self._storage.create_policy(ctx.org_id, created, rows)
            except UniqueKeyTaken as error:
                raise PreconditionFailed(
                    "the tenant's retention policy was written meanwhile"
                ) from error
            if not landed:
                raise PreconditionFailed(f"retention policy {created.id} is written already")
            await self._relay_all(ctx, rows)
            return created
        if policy.version != stored.version:
            raise PreconditionFailed(f"retention policy {stored.id} is at version {stored.version}")
        # The copy starts from the stored row: its id and provenance stay.
        updated = stored.model_copy(
            update={
                "policy": policy.policy,
                "projects": policy.projects,
                "version": stored.version + 1,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, UPDATED, updated.id, updated.version),)
        await self._storage.write_policy(ctx.org_id, updated, stored.version, rows)
        await self._relay_all(ctx, rows)
        return updated

    # A session's snapshot.

    async def take_snapshot(self, ctx: TenantContext, session: AgentSession) -> SessionRetention:
        ctx.require(Permission.WRITE)
        stored = await self._storage.read_snapshot(ctx.org_id, session.id)
        if stored is not None:
            return stored
        project_id = await self._project_of(ctx, session)
        tenant = await self._storage.read_policy(ctx.org_id)
        policy = effective(tenant, project_id)
        now = self._clock()
        at_rest = policy.storage_mode is StorageMode.SEALED
        content, shape = expiries(policy, now, at_rest, now)
        snapshot = SessionRetention(
            id=new_id(),
            created_at=now,
            session_id=session.id,
            project_id=project_id,
            policy=policy,
            policy_version=0 if tenant is None else tenant.version,
            at_rest=at_rest,
            content_expires_at=content,
            shape_expires_at=shape,
        )
        return await self._storage.create_snapshot(ctx.org_id, snapshot)

    async def _project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
        """The project of the session it came from, when it came from one
        that has a snapshot; otherwise the one the platform names for it."""
        came_from = session.parent_id or session.handed_off_from
        if came_from is not None:
            source = await self._storage.read_snapshot(ctx.org_id, came_from)
            if source is not None:
                return source.project_id
        return await self._projects.project_of(ctx, session)

    async def get_snapshot(self, ctx: TenantContext, session_id: UUID) -> SessionRetention:
        ctx.require(Permission.READ)
        stored = await self._storage.read_snapshot(ctx.org_id, session_id)
        if stored is None:
            raise NotFound(f"no retention snapshot of session {session_id}")
        return stored

    async def erase_content(self, ctx: TenantContext, session_id: UUID) -> SessionRetention:
        ctx.require(Permission.MANAGE_MEMBERS)
        snapshot = await self.get_snapshot(ctx, session_id)
        if snapshot.content_expired_at is not None:
            return snapshot
        # The sweep's own steps, once: the engine's revocation stands even
        # when the key service reports nothing, so the content is gone here.
        _, report = await self._expire_content(ctx.org_id, ctx, snapshot)
        now = self._clock()
        for _ in range(ERASE_WRITES):
            done = SessionRetention.model_validate(
                {
                    **snapshot.model_dump(),
                    "content_expired_at": now,
                    "destruction": report,
                    "version": snapshot.version + 1,
                }
            )
            if await self._storage.write_snapshot(ctx.org_id, done, snapshot.version):
                return done
            snapshot = await self.get_snapshot(ctx, session_id)
            if snapshot.content_expired_at is not None:
                return snapshot
        # A sweep that keeps writing the snapshot takes the erasure up at
        # the content's expiry, and each of its steps answers as before.
        return snapshot

    # The sweep.

    async def sweep(self, rctx: RequestContext) -> int:
        now = self._clock()
        behind = await self._storage.read_behind(self._options.sweep_batch)
        for org_id, snapshot, tenant in behind:
            try:
                current = effective(tenant, snapshot.project_id)
                # A write that loses its compare-and-set leaves the snapshot
                # to the next pass, which reads it again.
                await self._storage.write_snapshot(
                    org_id, folded(snapshot, current, tenant.version, now), snapshot.version
                )
            except Exception:
                # The snapshot stays behind for the next pass; every other
                # tenant's fold, and every expiry due, goes on in this one.
                log.exception(
                    "session %s of org %s stays behind its policy: its fold failed",
                    snapshot.session_id,
                    org_id,
                )
        due = await self._storage.read_due(now, self._options.sweep_batch)
        contexts: dict[UUID, TenantContext | None] = {}
        for org_id, snapshot in due:
            try:
                if org_id not in contexts:
                    contexts[org_id] = await self._context(rctx, org_id)
                await self._expire(org_id, contexts[org_id], snapshot, now)
            except Exception:
                log.exception(
                    "session %s of org %s waits for its next attempt: its retention failed",
                    snapshot.session_id,
                    org_id,
                )
                await self._defer(org_id, snapshot, now)
        return max(len(behind), len(due))

    async def _context(self, rctx: RequestContext, org_id: UUID) -> TenantContext | None:
        """The tenant's service context, or None for a tenant deleted: its
        sessions and their history go with its own purge."""
        try:
            return await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)
        except InvalidCredential:
            return None

    async def _expire(
        self, org_id: UUID, ctx: TenantContext | None, snapshot: SessionRetention, now: datetime
    ) -> None:
        """What a due snapshot asks for, then one write of it. The content and
        the shape each finish on their own: what finished is recorded, and
        what cannot finish yet takes the snapshot out of every pass's read
        until its next attempt. Each step is safe to take again."""
        update: dict[str, object] = {"next_attempt_at": None}
        waits = False
        if content_due(snapshot, now):
            gone, report = await self._expire_content(org_id, ctx, snapshot)
            if gone:
                update |= {"content_expired_at": now, "destruction": report}
            else:
                waits = True
        if shape_due(snapshot, now):
            if ctx is None or await self._mark(ctx, snapshot):
                update["shape_expired_at"] = now
            else:
                waits = True
        if waits:
            update["next_attempt_at"] = now + self._options.retry_after
        done = SessionRetention.model_validate(
            {**snapshot.model_dump(), **update, "version": snapshot.version + 1}
        )
        await self._storage.write_snapshot(org_id, done, snapshot.version)

    async def _defer(self, org_id: UUID, snapshot: SessionRetention, now: datetime) -> None:
        """The snapshot out of every pass's read until its next attempt, after
        a pass that failed on it; a write that fails too leaves it as it was."""
        later = snapshot.model_copy(
            update={
                "next_attempt_at": now + self._options.retry_after,
                "version": snapshot.version + 1,
            }
        )
        try:
            await self._storage.write_snapshot(org_id, later, snapshot.version)
        except Exception:
            log.exception("session %s of org %s stays due", snapshot.session_id, org_id)

    async def _expire_content(
        self, org_id: UUID, ctx: TenantContext | None, snapshot: SessionRetention
    ) -> tuple[bool, KeyDestruction | None]:
        """Whether the session's key is gone, and the key service's report.
        The engine revokes the key, a session marked deleted included, and
        the tenant's key service destroys it. The key is gone only when one
        of them says so; then the audit entry is written. A session the
        tenant holds no key of has nothing to destroy, and is gone with no
        entry. A tenant deleted has no context, so its service alone can
        say so."""
        session_id = snapshot.session_id
        revoked_at: datetime | None = None
        keyless = False
        if ctx is not None:
            try:
                revoked_at = (await self._privacy.revoke_key(ctx, session_id)).revoked_at
            except NotFound:
                keyless = True
        report = await self._destroy(org_id, session_id)
        if report is None and revoked_at is None:
            return keyless, None
        if ctx is not None:
            await self._audit(ctx, snapshot, report, revoked_at)
        return True, report

    async def _destroy(self, org_id: UUID, session_id: UUID) -> KeyDestruction | None:
        """The session's key destroyed by the tenant's key service, and its
        report; None when that service holds the tenant's key alone."""
        custody = self._keys.custody(org_id)
        if custody is None:
            return None
        try:
            return await custody.destroy(org_id, session_id)
        except InfraException as error:
            if error.code != KeyRefused.code:
                raise
            # The tenant revoked its own key: nothing of it opens, and its
            # service reports nothing more. The engine's revocation stands.
            return None

    async def _audit(
        self,
        ctx: TenantContext,
        snapshot: SessionRetention,
        report: KeyDestruction | None,
        revoked_at: datetime | None,
    ) -> None:
        """The audit entry of a destruction: the key service's report as it
        came, or, with none, that no service reported it and when the engine
        revoked the key."""
        session_id = snapshot.session_id
        facts: dict[str, object]
        if report is not None:
            facts = {
                "reported": True,
                "service": report.service,
                "key": report.key,
                "destroyed_at": report.destroyed_at.isoformat(),
                "receipt": report.receipt,
            }
        else:
            facts = {
                "reported": False,
                "revoked_at": None if revoked_at is None else revoked_at.isoformat(),
            }
        expires = snapshot.content_expires_at or snapshot.created_at
        entry = audit_event(
            ctx, derived_id(session_id, expires, KEY_DESTROYED), KEY_DESTROYED, session_id, facts
        )
        await self._events.append_event(ctx, entry)

    async def _mark(self, ctx: TenantContext, snapshot: SessionRetention) -> bool:
        """The session marked deleted, its shape past its life; the engine's
        purge removes it. False when a loop is still open: the next pass
        tries again. A loop that waits parked, on a person or on anything
        else that may never come, is cancelled under the service context,
        so the run that ends it leaves the session for the next pass to
        mark."""
        try:
            await self._sessions.delete_session(ctx, snapshot.session_id)
        except NotFound:
            return True
        except ValidationFailed:
            await self._cancel_parked(ctx, snapshot)
            return False
        return True

    async def _cancel_parked(self, ctx: TenantContext, snapshot: SessionRetention) -> None:
        """A `cancel` control on a parked session's loop, through the inbox,
        which clears the park and asks for the run that ends the loop. A
        loop a run holds, or one an input is about to wake, ends by itself."""
        session = await self._sessions.get_session(ctx, snapshot.session_id)
        if session.status is not SessionStatus.PARKED:
            return
        expires = snapshot.shape_expires_at or snapshot.created_at
        step_id = derived_id(snapshot.session_id, expires, SHAPE_CANCEL)
        cancel = Step(
            id=step_id,
            created_at=self._clock(),
            session_id=snapshot.session_id,
            loop_id=step_id,
            type=StepType.CONTROL,
            actor=Actor.ENGINE,
            origin=Origin.ENGINE,
            header=ControlHeader(command=ControlCommand.CANCEL),
        )
        await self._sessions.receive(ctx, snapshot.session_id, [cancel])
        log.info(
            "session %s of org %s parked past its shape's life: its loop is cancelled",
            snapshot.session_id,
            ctx.org_id,
        )

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        await self._relay.relay_all(ctx.org_id, rows)
