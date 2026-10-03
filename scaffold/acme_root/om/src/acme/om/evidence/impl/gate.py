from uuid import UUID

from acme.infra.exceptions import InfraException
from acme.om.agents.gate import ResultGateInterface
from acme.om.agents.types.result import Claim, Result, Verdict
from acme.om.base import Platform
from acme.om.context import Permission, TenantContext
from acme.om.evidence.rules import Reading, judge, policy_key, refused
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.record import RunPurpose
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import PlatformException
from acme.om.projects.policies import SessionProjectsInterface


class ResultGateOptions(Platform):
    max_cited: int = 500  # ids one result may cite
    max_validations: int = 100  # validations at one head the gate reads
    max_runs: int = 100_000  # runs of those validations the gate reads


class ResultGateEvidenceImpl(ResultGateInterface):
    """The gate that knows what evidence is. It reads the runs a result
    cites, the session's work product from the system that keeps it, the
    policy of the project `projects` answers for the session, never one the
    work product names, and every validation at the delivered head with
    every run it lists, and judges them (`rules.judge`). What it cannot read
    in full it does not judge: it refuses."""

    def __init__(
        self,
        storage: EvidenceStorageInterface,
        work_product: WorkProductInterface,
        projects: SessionProjectsInterface,
        options: ResultGateOptions | None = None,
    ) -> None:
        self._storage = storage
        self._work_product = work_product
        self._projects = projects
        self._options = options or ResultGateOptions()

    async def check(self, ctx: TenantContext, session_id: UUID, result: Result) -> Verdict:
        ctx.require(Permission.READ)
        cited = set(result.evidence)
        if len(cited) > self._options.max_cited:
            return refused(
                f"a claim cites at most {self._options.max_cited} runs; cite the ones that show it"
            )
        runs = await self._storage.read_cited(
            ctx.org_id, session_id, sorted(cited), self._options.max_runs
        )
        named = {
            found for record in runs for found in (record.id, record.step_id, record.validation_id)
        }
        reading = Reading(cited=tuple(runs), unresolved=tuple(sorted(cited - named, key=str)))
        if result.claim is Claim.FAILED or reading.unresolved or not reading.cited:
            return judge(result.claim, reading)
        return judge(result.claim, await self._read(ctx, session_id, reading))

    async def _read(self, ctx: TenantContext, session_id: UUID, reading: Reading) -> Reading:
        try:
            delivery = await self._work_product.delivered(ctx, session_id)
        except (PlatformException, InfraException) as error:
            return Reading(cited=reading.cited, unread=error.message)
        if delivery is None or not delivery.changes_work_product:
            return Reading(cited=reading.cited, delivery=delivery)
        project_id = await self._projects.project_of(ctx, session_id)
        key = None if project_id is None else policy_key(project_id)
        policy = None if key is None else await self._storage.read_policy(ctx.org_id, key)
        bound = self._options.max_validations
        found = await self._storage.read_validations(
            ctx.org_id, session_id, delivery.head, bound + 1
        )
        if len(found) > bound:
            return Reading(
                cited=reading.cited,
                unread=f"more than {bound} validations ran at {delivery.head}",
            )
        validations = tuple(
            validation
            for validation in found
            if validation.purpose is RunPurpose.VALIDATION and validation.project == key
        )
        records = await self._storage.read_validation_records(
            ctx.org_id,
            session_id,
            [validation.id for validation in validations],
            self._options.max_runs + 1,
        )
        if len(records) > self._options.max_runs:
            return Reading(
                cited=reading.cited,
                unread=f"more than {self._options.max_runs} runs to judge at once",
            )
        return Reading(
            cited=reading.cited,
            delivery=delivery,
            policy=policy,
            validations=validations,
            records=tuple(records),
        )
