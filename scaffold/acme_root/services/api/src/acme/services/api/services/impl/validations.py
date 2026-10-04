from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
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
        record = None
        if session.run_id is not None:
            # The session was read in its tenant first: the evidence reads its
            # runs by the session's id alone.
            page = await self._evidence.get_runs(ctx, session.id, None, LIMIT_MAX)
            record = next((each for each in page.items if each.id == session.run_id), None)
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
            passed=None if record is None else record.passing,
            run=None if record is None else execution_view(record),
        )
