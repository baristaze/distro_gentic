from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.base import Platform, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.rules import policy_key
from acme.om.exceptions import NotFound, PreconditionFailed, ValidationFailed
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row, versioned_row
from acme.om.platform_agents.manager import PlatformAgentsManagerInterface
from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.types.validation import (
    ValidationSession,
    ValidationStart,
    ValidationStatus,
)
from acme.om.tenancy import TenancyManagerInterface
from acme.om.work.types.work_item import ValidationPayload, WorkKind, work_row_kind

CREATED = "platform_agents.validation_session.created"
UPDATED = "platform_agents.validation_session.updated"


class PlatformAgentsOptions(Platform):
    purge_batch: int = 1000  # validation sessions one purge statement deletes at most


class PlatformAgentsManagerImpl(PlatformAgentsManagerInterface):
    def __init__(
        self,
        storage: PlatformAgentsStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        evidence: EvidenceManagerInterface,
        options: PlatformAgentsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._evidence = evidence
        self._options = options
        self._clock = clock

    async def start_validation(
        self, ctx: TenantContext, start: ValidationStart
    ) -> ValidationSession:
        ctx.require(Permission.WRITE)
        # Refused before anything is written: a check its project does not
        # declare would only fail for good on the worker. The policy is read
        # in the caller's tenant, so another tenant's project has none.
        policy = await self._evidence.get_policy(ctx, policy_key(start.project_id))
        if all(each.name != start.check_name for each in policy.checks):
            raise ValidationFailed(
                f"the project {start.project_id} declares no check {start.check_name}"
            )
        now = self._clock()
        session = ValidationSession(
            id=start.id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            project_id=start.project_id,
            check_name=start.check_name,
            head=start.head,
            base=start.base,
        )
        # Its work lands with the session, on the platform's own lane: the
        # platform's worker runs it on a fresh executor. No loop is asked
        # for, so no runner claims it and no model is called.
        rows = (
            versioned_row(ctx, CREATED, session.id, session.version),
            outbox_row(
                ctx,
                work_row_kind(WorkKind.VALIDATION),
                session.id,
                ValidationPayload().model_dump(mode="json"),
            ),
        )
        if not await self._storage.create_validation(ctx.org_id, session, rows):
            return await self.get_validation(ctx, start.id)
        await self._relay_all(ctx, rows)
        return session

    async def get_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSession:
        ctx.require(Permission.READ)
        found = await self._storage.read_validation(ctx.org_id, session_id)
        if found is None:
            raise NotFound(f"validation session {session_id} not found")
        return found

    async def run_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSession:
        ctx.require(Permission.WRITE)
        stored = await self.get_validation(ctx, session_id)
        if stored.status is ValidationStatus.FINISHED:
            return stored
        # The evidence keeps the run with the session's id, and answers it
        # again when asked again: a retry after the run was kept runs
        # nothing more.
        validation = await self._evidence.run_check(
            ctx, stored.id, stored.project_id, stored.check_name, stored.head, stored.base
        )
        if len(validation.records) != 1:
            raise ValidationFailed(
                f"validation session {session_id} kept {len(validation.records)} runs of its "
                "one check"
            )
        return await self.finish_validation(ctx, session_id, validation.records[0])

    async def finish_validation(
        self, ctx: TenantContext, session_id: UUID, run_id: UUID
    ) -> ValidationSession:
        ctx.require(Permission.WRITE)
        stored = await self.get_validation(ctx, session_id)
        if stored.status is ValidationStatus.FINISHED:
            if stored.run_id == run_id:
                return stored
            raise PreconditionFailed(
                f"validation session {session_id} finished already, with run {stored.run_id}"
            )
        now = self._clock()
        finished = stored.model_copy(
            update={
                "status": ValidationStatus.FINISHED,
                "run_id": run_id,
                "finished_at": now,
                "version": stored.version + 1,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, UPDATED, finished.id, finished.version),)
        await self._storage.write_validation(ctx.org_id, finished, stored.version, rows)
        await self._relay_all(ctx, rows)
        return finished

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        await self._relay.relay_all(ctx.org_id, rows)
