from collections.abc import Sequence
from uuid import UUID

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.types.record import ExecutionRecord
from acme.om.evidence.types.validation import Validation
from acme.om.exceptions import NotFound
from acme.om.intake import IntakeManagerInterface
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.header import ToolResponseHeader
from acme.om.steps.types.step import Step
from acme.om.workspaces import WorkspacesManagerInterface
from acme.services.api.services.evidence import EvidenceServiceInterface
from acme.services.api.services.impl.tenancy import decode_cursor, encode_cursor
from acme.services.api.types.common import LIMIT_MAX, clamp_limit
from acme.services.api.types.evidence import (
    CasesView,
    DeliveryView,
    ExecutionPageView,
    ExecutionView,
    ReportView,
    ValidationView,
    WorkHandleView,
)

EXECUTIONS = "executions"


def execution_view(record: ExecutionRecord) -> ExecutionView:
    return ExecutionView(
        id=record.id,
        purpose=record.purpose,
        step_id=record.step_id,
        validation_id=record.validation_id,
        project=record.project,
        version=record.version,
        dirty=record.dirty,
        image=record.environment.image,
        host=record.host,
        isolation=record.isolation,
        executor=record.executor,
        check=record.check,
        check_version=record.check_version,
        started_at=record.started_at,
        finished_at=record.finished_at,
        outcome=record.outcome,
        cases=CasesView.model_validate(record.cases),
        provenance=record.provenance,
        abort=record.abort,
    )


def validation_view(validation: Validation) -> ValidationView:
    return ValidationView(
        id=validation.id,
        created_at=validation.created_at,
        purpose=validation.purpose,
        project=validation.project,
        version=validation.version,
        source=validation.source,
        executor=validation.executor,
        results_sha256=validation.results_sha256,
        records=list(validation.records),
    )


def report_of(history: Sequence[Step]) -> ReportView | None:
    """The latest result the gate accepted, read off its tool response's
    header, so a session whose content is revoked still shows it."""
    for step in reversed(history):
        header = step.header
        if isinstance(header, ToolResponseHeader) and header.accepted is not None:
            return ReportView(
                seq=step.seq,
                accepted_at=step.created_at,
                outcome=header.accepted.outcome,
                verified=header.accepted.verified,
            )
    return None


class EvidenceServiceImpl(EvidenceServiceInterface):
    def __init__(
        self,
        sessions: AgentSessionsManagerInterface,
        evidence: EvidenceManagerInterface,
        workspaces: WorkspacesManagerInterface,
        steps: StepsManagerInterface,
        intake: IntakeManagerInterface,
    ) -> None:
        self._sessions = sessions
        self._evidence = evidence
        self._workspaces = workspaces
        self._steps = steps
        self._intake = intake

    async def get_executions(
        self, ctx: TenantContext, session_id: UUID, cursor: str | None, limit: int
    ) -> ExecutionPageView:
        after = decode_cursor(EXECUTIONS, cursor) if cursor else None
        # The session first: the evidence reads by its id alone.
        await self._sessions.get_session(ctx, session_id)
        page = await self._evidence.get_runs(ctx, session_id, after, clamp_limit(limit))
        last = page.items[-1].id if page.items and page.has_more else None
        return ExecutionPageView(
            items=[execution_view(record) for record in page.items],
            next_cursor=None if last is None else encode_cursor(EXECUTIONS, last),
        )

    async def get_validations(
        self, ctx: TenantContext, session_id: UUID, limit: int
    ) -> list[ValidationView]:
        await self._sessions.get_session(ctx, session_id)
        found = await self._evidence.get_validations(ctx, session_id, clamp_limit(limit))
        return [validation_view(validation) for validation in found]

    async def get_delivery(self, ctx: TenantContext, session_id: UUID) -> DeliveryView:
        await self._sessions.get_session(ctx, session_id)
        try:
            workspace = await self._workspaces.get_workspace(ctx, session_id)
        except NotFound:
            # A session that was never pinned to a workspace has no branch.
            workspace = None
        work = await self._intake.get_work(ctx, session_id)
        return DeliveryView(
            project_id=None if workspace is None else workspace.project_id,
            branch=None if workspace is None else workspace.branch,
            branch_seen=workspace is not None and workspace.branch_seen,
            work=[
                WorkHandleView(kind=bound.kind, handle=bound.handle, bound_at=bound.created_at)
                for bound in work
            ],
            report=report_of(await self._history(ctx, session_id)),
        )

    async def _history(self, ctx: TenantContext, session_id: UUID) -> list[Step]:
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self._steps.get_steps(ctx, session_id, after, LIMIT_MAX)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps
