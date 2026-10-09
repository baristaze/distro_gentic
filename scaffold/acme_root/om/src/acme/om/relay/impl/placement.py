"""Two decorators the root wires around placement. Trust's question of where
a session's next call runs, answered with the host that holds the session's
workspace once one does. And placement's claim for a host, which hands over
an `exec` item only once the relay has started it."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.placement.manager import PlacementManagerInterface
from acme.om.placement.types.claimant import Claimant, ClaimantReport
from acme.om.relay.manager import RelayManagerInterface
from acme.om.relay.storage import RelayStorageInterface
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.types.work_item import WorkItem, WorkKind


class PlacementRelayedImpl(PlacementInterface):
    """A session pinned to its tenant's hosts runs each call on the host that
    holds its workspace, its executor. Until one does, `inner` answers, and
    refuses the call: it never runs on one of the platform's machines."""

    def __init__(self, inner: PlacementInterface, storage: RelayStorageInterface) -> None:
        self._inner = inner
        self._storage = storage

    async def inside_wall(self, org_id: UUID, session_id: UUID) -> bool:
        return await self._inner.inside_wall(org_id, session_id)

    async def executor_of(self, org_id: UUID, session_id: UUID) -> Executor:
        if not await self._inner.inside_wall(org_id, session_id):
            return await self._inner.executor_of(org_id, session_id)
        binding = await self._storage.read_binding(org_id, session_id)
        if binding is None:
            return await self._inner.executor_of(org_id, session_id)
        # A host is named by itself: its credentials rotate under it.
        return Executor(
            kind=ExecutorKind.HOST, credential_id=binding.host_id, label=binding.host_name
        )


class PlacementClaimsRelayedImpl(PlacementManagerInterface):
    """Placement as the hosts claim through it: an `exec` item a claim took
    is handed over only once the relay started it, so an unsafe item a claim
    took before, a settled one, or a lost run's command is settled at the
    claim and never reaches a host. `relay` answers at call time, as the
    root builds the relay after the hosts."""

    def __init__(
        self, inner: PlacementManagerInterface, relay: Callable[[], RelayManagerInterface]
    ) -> None:
        self._inner = inner
        self._relay = relay

    async def lane_for(self, org_id: UUID, item: WorkItem) -> str:
        return await self._inner.lane_for(org_id, item)

    async def claim_for(
        self, rctx: RequestContext, claimant: Claimant, lease: timedelta
    ) -> tuple[TenantContext, WorkItem] | None:
        while True:
            claimed = await self._inner.claim_for(rctx, claimant, lease)
            if claimed is None:
                return None
            ctx, item = claimed
            if item.kind != WorkKind.EXEC or await self._relay().start(ctx, item):
                return claimed

    async def held_for(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        claim_token: UUID,
    ) -> WorkItem:
        return await self._inner.held_for(rctx, claimant, org_id, item_id, claim_token)

    async def report_for(
        self, rctx: RequestContext, claimant: Claimant, org_id: UUID, report: ClaimantReport
    ) -> WorkItem:
        return await self._inner.report_for(rctx, claimant, org_id, report)

    async def extend_for(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        claim_token: UUID,
        lease: timedelta,
    ) -> WorkItem:
        return await self._inner.extend_for(rctx, claimant, org_id, item_id, claim_token, lease)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)
