"""What the root wires around placement. Trust's question of where a
session's next call runs, answered with the host that holds the session's
workspace once one does. Placement's claim for a host, which hands over an
`exec` item only once the exec relay has started it. And the session tree an
item serves, which a claim reads for a person's own client."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.context import RequestContext, TenantContext
from acme.om.exec_relay.manager import ExecRelayManagerInterface
from acme.om.exec_relay.storage import ExecRelayStorageInterface
from acme.om.placement.kinds import PlacementWorkKind
from acme.om.placement.manager import PlacementManagerInterface
from acme.om.placement.types.claimant import Claimant, ClaimantReport, Holding
from acme.om.trust.placement import PlacementInterface
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.types.work_item import WorkItem


class PlacementRelayedImpl(PlacementInterface):
    """A session pinned to its tenant's hosts runs each call on the host that
    holds its workspace, its executor. Until one does, `inner` answers, and
    refuses the call: it never runs on one of the platform's VMs."""

    def __init__(self, inner: PlacementInterface, storage: ExecRelayStorageInterface) -> None:
        self._inner = inner
        self._storage = storage

    async def inside_wall(self, org_id: UUID, agent_session_id: UUID) -> bool:
        return await self._inner.inside_wall(org_id, agent_session_id)

    async def executor_of(self, org_id: UUID, agent_session_id: UUID) -> Executor:
        if not await self._inner.inside_wall(org_id, agent_session_id):
            return await self._inner.executor_of(org_id, agent_session_id)
        binding = await self._storage.read_binding(org_id, agent_session_id)
        if binding is None:
            return await self._inner.executor_of(org_id, agent_session_id)
        # A host is named by itself: its credentials rotate under it.
        return Executor(
            kind=ExecutorKind.HOST, credential_id=binding.host_id, label=binding.host_name
        )


class PlacementClaimsRelayedImpl(PlacementManagerInterface):
    """Placement as the hosts claim through it: an `exec` item a claim took
    is handed over only once the exec relay started it, so an unsafe item a claim
    took before, a settled one, or a lost run's command is settled at the
    claim and never reaches a host. `exec_relay` answers at call time, as the
    root builds the exec relay after the hosts."""

    def __init__(
        self, inner: PlacementManagerInterface, exec_relay: Callable[[], ExecRelayManagerInterface]
    ) -> None:
        self._inner = inner
        self._exec_relay = exec_relay

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
            if item.kind != PlacementWorkKind.EXEC or await self._exec_relay().start(ctx, item):
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

    async def holding_for(self, claimant: Claimant, org_id: UUID) -> Holding:
        return await self._inner.holding_for(claimant, org_id)

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


class ItemTreesImpl:
    """The root of the session tree an item serves (`placement`'s `TreeOf`),
    which a claim reads for a person's own client: the session the item
    names, read up to its tree's root. An instance a run made for a session
    under an id of its own is no session: the session it is made for is the
    one its prepare names, or the one its binding keeps. None when the item
    names no session either reads."""

    def __init__(
        self, sessions: AgentSessionStorageInterface, storage: ExecRelayStorageInterface
    ) -> None:
        self._sessions = sessions
        self._storage = storage

    async def __call__(self, org_id: UUID, item: WorkItem) -> UUID | None:
        named = _named(item.payload.get("agent_session_id"))
        if named is None:
            return None
        session = await self._sessions.read_agent_session(org_id, named)
        if session is None:
            owner = _named(item.payload.get("instance_of"))
            if owner is None:
                binding = await self._storage.read_binding(org_id, named)
                owner = None if binding is None else binding.instance_of
            if owner is None:
                return None
            session = await self._sessions.read_agent_session(org_id, owner)
        return None if session is None else session.root_id


def _named(value: object) -> UUID | None:
    """The id a payload's field names, or None when it names none."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
