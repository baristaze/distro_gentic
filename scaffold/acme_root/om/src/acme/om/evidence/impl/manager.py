from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, Role, TenantContext
from acme.om.evidence.collector import collect, digest
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.manager import EvidenceManagerInterface
from acme.om.evidence.rules import execution_request, policy_key, protection_target
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.inference import Inference, InferenceKind, InferencePage
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import ExecutionRecord, ExecutionRecordPage, RunPurpose
from acme.om.evidence.types.validation import ExecutionRequest, Validation
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import (
    NotAuthorized,
    NotFound,
    PreconditionFailed,
    UniqueKeyTaken,
    ValidationFailed,
)
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.types.policy import Target

CREATED = "evidence.validation_policy.created"
UPDATED = "evidence.validation_policy.updated"


class EvidenceOptions(Platform):
    max_limit: int = 200  # rows one page holds
    purge_batch: int = 1000  # rows of each table one purge statement deletes at most


class EvidenceManagerImpl(EvidenceManagerInterface):
    def __init__(
        self,
        storage: EvidenceStorageInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        executor: ExecutorInterface,
        work_product: WorkProductInterface,
        projects: SessionProjectsInterface,
        options: EvidenceOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._relay = relay
        self._executor = executor
        self._work_product = work_product
        self._projects = projects
        self._options = options
        self._clock = clock

    # The policy.

    async def get_policy(self, ctx: TenantContext, project: str) -> ValidationPolicy:
        ctx.require(Permission.READ)
        stored = await self._storage.read_policy(ctx.org_id, project)
        if stored is None:
            raise NotFound(f"the project {project} declares no validation policy")
        return stored

    async def write_policy(self, ctx: TenantContext, policy: ValidationPolicy) -> ValidationPolicy:
        ctx.require(Permission.MANAGE_MEMBERS)
        if ctx.role is Role.SERVICE:
            raise NotAuthorized("a person declares a validation policy, never a service")
        stored = await self._storage.read_policy(ctx.org_id, policy.project)
        now = self._clock()
        if stored is None:
            created = ValidationPolicy.model_validate(
                {
                    **policy.model_dump(),
                    "created_at": now,
                    "updated_at": now,
                    "created_by": ctx.user_id,
                    "updated_by": ctx.user_id,
                    "version": 1,
                }
            )
            rows = (versioned_row(ctx, CREATED, created.id, created.version),)
            try:
                landed = await self._storage.create_policy(ctx.org_id, created, rows)
            except UniqueKeyTaken as error:
                raise PreconditionFailed(
                    f"the policy of {policy.project} was written meanwhile"
                ) from error
            if not landed:
                raise PreconditionFailed(f"validation policy {created.id} is written already")
            await self._relay_all(ctx, rows)
            return created
        if policy.version != stored.version:
            raise PreconditionFailed(
                f"validation policy {stored.id} is at version {stored.version}"
            )
        # The copy starts from the stored row: its id, its project, and its
        # provenance stay.
        updated = stored.model_copy(
            update={
                "checks": policy.checks,
                "requirements": policy.requirements,
                "protected": policy.protected,
                "version": stored.version + 1,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows = (versioned_row(ctx, UPDATED, updated.id, updated.version),)
        await self._storage.write_policy(ctx.org_id, updated, stored.version, rows)
        await self._relay_all(ctx, rows)
        return updated

    async def protection(
        self, ctx: TenantContext, session_id: UUID, paths: Sequence[str]
    ) -> Target:
        ctx.require(Permission.READ)
        project_id = await self._projects.project_of(ctx, session_id)
        policy = (
            None
            if project_id is None
            else await self._storage.read_policy(ctx.org_id, policy_key(project_id))
        )
        return protection_target(policy, paths)

    # The runs.

    async def record_run(self, ctx: TenantContext, record: ExecutionRecord) -> ExecutionRecord:
        ctx.require(Permission.WRITE)
        if record.purpose is not RunPurpose.WORK:
            raise ValidationFailed("only the executor writes a baseline or a validation run")
        await self._storage.create_record(ctx.org_id, record)
        return record

    async def get_runs(
        self, ctx: TenantContext, session_id: UUID, after: UUID | None, limit: int
    ) -> ExecutionRecordPage:
        ctx.require(Permission.READ)
        limit = self._clamp(limit)
        rows = await self._storage.read_records(ctx.org_id, session_id, after, limit + 1)
        return ExecutionRecordPage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    async def record_inference(self, ctx: TenantContext, inference: Inference) -> Inference:
        ctx.require(Permission.WRITE)
        runs = set(inference.runs)
        found = await self._storage.read_cited(
            ctx.org_id, inference.session_id, sorted(runs), len(runs) + 1
        )
        missing = runs - {record.id for record in found}
        if missing:
            raise ValidationFailed(
                f"an inference cites runs its session does not hold: {sorted(map(str, missing))}"
            )
        if inference.resolves is not None:
            hypothesis = await self._storage.read_inference(ctx.org_id, inference.resolves)
            if (
                hypothesis is None
                or hypothesis.session_id != inference.session_id
                or hypothesis.kind is not InferenceKind.HYPOTHESIS
            ):
                raise ValidationFailed(
                    f"{inference.resolves} is no hypothesis of session {inference.session_id}"
                )
        await self._storage.create_inference(ctx.org_id, inference)
        return inference

    async def get_inferences(
        self, ctx: TenantContext, session_id: UUID, after: UUID | None, limit: int
    ) -> InferencePage:
        ctx.require(Permission.READ)
        limit = self._clamp(limit)
        rows = await self._storage.read_inferences(ctx.org_id, session_id, after, limit + 1)
        return InferencePage(items=tuple(rows[:limit]), has_more=len(rows) > limit)

    # Validation.

    async def validate(
        self, ctx: TenantContext, session_id: UUID, purpose: RunPurpose
    ) -> Validation:
        ctx.require(Permission.WRITE)
        delivery = await self._work_product.delivered(ctx, session_id)
        if delivery is None:
            raise PreconditionFailed(f"session {session_id} holds no work product to validate")
        project_id = await self._projects.project_of(ctx, session_id)
        if project_id is None:
            raise PreconditionFailed(
                f"session {session_id} belongs to no project, so no validation policy applies"
            )
        policy = await self._storage.read_policy(ctx.org_id, policy_key(project_id))
        if policy is None:
            raise PreconditionFailed(f"the project {project_id} declares no validation policy")
        request = execution_request(
            session_id, policy, delivery, purpose, await self._executor.offer(ctx)
        )
        if isinstance(request, str):
            raise PreconditionFailed(request)
        report = await self._executor.run(ctx, request)
        if digest(report.results) != report.sha256:
            raise ValidationFailed("the results do not hash to what the executor wrote")
        validation_id = new_id()
        now = self._clock()
        records = collect(
            report.results,
            executor=report.executor,
            session_id=session_id,
            project=request.project,
            purpose=purpose,
            validation_id=validation_id,
            now=now,
        )
        _refuse_unasked(request, records)
        validation = Validation(
            id=validation_id,
            created_at=now,
            session_id=session_id,
            project=request.project,
            purpose=purpose,
            version=request.version,
            source=request.source,
            executor=report.executor,
            results_sha256=report.sha256,
            records=tuple(record.id for record in records),
        )
        await self._storage.create_validation(ctx.org_id, validation, records)
        return validation

    async def get_validations(
        self, ctx: TenantContext, session_id: UUID, limit: int
    ) -> tuple[Validation, ...]:
        ctx.require(Permission.READ)
        found = await self._storage.read_validations(
            ctx.org_id, session_id, None, self._clamp(limit)
        )
        return tuple(found)

    # The purges.

    async def purge_session(self, org_id: UUID, session_id: UUID) -> int:
        purged = 0
        while True:
            gone = await self._storage.purge_session(org_id, session_id, self._options.purge_batch)
            purged += gone
            if gone == 0:
                return purged

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    def _clamp(self, limit: int) -> int:
        return max(1, min(limit, self._options.max_limit))

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        if rows:
            await self._relay.relay_all(ctx.org_id, rows)


def _refuse_unasked(request: ExecutionRequest, records: Sequence[ExecutionRecord]) -> None:
    """The executor's results hold the checks it was asked for, at the version
    it was asked for, and nothing else."""
    asked = {check.name: check.version for check in request.checks}
    for record in records:
        if asked.get(record.check) != record.check_version:
            raise ValidationFailed(
                f"the results hold {record.check} {record.check_version}, which was not asked for"
            )
        if record.version != request.version:
            raise ValidationFailed(
                f"the results ran at {record.version}, not the {request.version} asked for"
            )
