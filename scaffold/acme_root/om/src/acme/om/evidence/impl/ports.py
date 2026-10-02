"""The evidence's ports when a root wires nothing of its own: an executor
that refuses every run and a work product that cannot be read, both loud;
and the work product a process keeps in memory, a test's and a single
process's."""

from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence.executor import ExecutorInterface
from acme.om.evidence.types.contract import Offer
from acme.om.evidence.types.validation import Delivery, ExecutionRequest, ExecutorReport
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import Unavailable


class ExecutorAbsentImpl(ExecutorInterface):
    """Loud: no executor is wired, so nothing is validated, and nothing
    pretends it was."""

    async def offer(self, ctx: TenantContext) -> Offer:
        raise Unavailable("this platform has no executor to validate on")

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        raise Unavailable("this platform has no executor to validate on")


class WorkProductAbsentImpl(WorkProductInterface):
    """Loud: no work product is wired, so none is read, and the gate counts
    no success on what it cannot see."""

    async def delivered(self, ctx: TenantContext, session_id: UUID) -> Delivery | None:
        raise Unavailable("this platform reads no work product")


class WorkProductMemoryImpl(WorkProductInterface):
    """Each session's work product as this process was told it."""

    def __init__(self) -> None:
        self._deliveries: dict[tuple[UUID, UUID], Delivery] = {}

    def deliver(self, org_id: UUID, session_id: UUID, delivery: Delivery) -> None:
        self._deliveries[(org_id, session_id)] = delivery

    async def delivered(self, ctx: TenantContext, session_id: UUID) -> Delivery | None:
        return self._deliveries.get((ctx.org_id, session_id))
