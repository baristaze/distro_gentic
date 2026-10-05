from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.rules import policy_key, session_refusal
from acme.om.evidence.types.record import ExecutionRecord
from acme.om.platform_agents import PlatformAgentsManagerInterface
from acme.om.platform_agents.types.validation import ValidationSession, ValidationStart
from acme.services.api.services.impl.evidence import execution_view
from acme.services.api.services.validations import ValidationsServiceInterface
from acme.services.api.types.common import LIMIT_MAX
from acme.services.api.types.validations import StartValidationRequest, ValidationSessionView


class ValidationsServiceImpl(ValidationsServiceInterface):
    def __init__(
        self, platform_agents: PlatformAgentsManagerInterface, evidence: EvidenceManagerInterface
    ) -> None:
        self._platform_agents = platform_agents
        self._evidence = evidence

    async def start_validation(
        self, ctx: TenantContext, body: StartValidationRequest, session_id: UUID
    ) -> ValidationSessionView:
        start = ValidationStart(
            id=session_id,
            project_id=body.project_id,
            check_name=body.check,
            head=body.head,
            base=body.base,
        )
        return await self._view(ctx, await self._platform_agents.start_validation(ctx, start))

    async def get_validation(self, ctx: TenantContext, session_id: UUID) -> ValidationSessionView:
        return await self._view(ctx, await self._platform_agents.get_validation(ctx, session_id))

    async def _view(self, ctx: TenantContext, session: ValidationSession) -> ValidationSessionView:
        runs: list[ExecutionRecord] = []
        record = None
        reason = None
        if session.run_id is not None:
            # The session was read in its tenant first: the evidence reads its
            # runs by the session's id alone.
            runs = await self._runs(ctx, session.id)
            record = next((each for each in runs if each.id == session.run_id), None)
        if record is not None:
            # The run passes at the grade its project's policy asks of the
            # check, never on a double or a dependency that was not there; a
            # rated check passes only as its requirements judge its trials.
            policy = await self._evidence.get_policy(ctx, policy_key(session.project_id))
            kept = await self._evidence.get_validations(ctx, session.id, 1)
            order = {run: at for at, run in enumerate(kept[0].records)} if kept else {}
            batch = [each for each in runs if each.validation_id == record.validation_id]
            reason = session_refusal(policy, record, batch, session.head, order)
        return ValidationSessionView(
            id=session.id,
            created_at=session.created_at,
            created_by=session.created_by,
            project_id=session.project_id,
            check=session.check_name,
            head=session.head,
            base=session.base,
            status=session.status,
            finished_at=session.finished_at,
            passed=None if record is None else reason is None,
            reason=reason,
            run=None if record is None else execution_view(record),
        )

    async def _runs(self, ctx: TenantContext, session_id: UUID) -> list[ExecutionRecord]:
        """Every run of the session, oldest first: a rated check's trials
        may fill more than one page."""
        runs: list[ExecutionRecord] = []
        after = None
        while True:
            page = await self._evidence.get_runs(ctx, session_id, after, LIMIT_MAX)
            runs.extend(page.items)
            if not page.has_more or not page.items:
                return runs
            after = page.items[-1].id
