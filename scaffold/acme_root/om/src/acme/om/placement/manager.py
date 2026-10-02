"""The placement swimlane: where each kind of a session's work runs, the
claim the control plane makes for a host or a daemon, and each tenant's
fair share of the loops, held at the claim."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from acme.om.context import OperatorContext, RequestContext, TenantContext
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.share import FairShare

if TYPE_CHECKING:
    # The work queue fixes its payloads by kind, and the payloads of the
    # kinds a host or a daemon runs are this namespace's, so the work item
    # is named here for the type checker alone.
    from acme.om.work.types.work_item import WorkItem


class PlacementManagerInterface(ABC):
    @abstractmethod
    async def lane_for(self, org_id: UUID, item: WorkItem) -> str:
        """Platform-internal: the lane an item is enqueued on, which the work
        manager asks at every enqueue, so no producer picks one. A loop goes
        to its tenant's lane, a lane of its own when its share says so and
        its plan tier's otherwise; a command to the host that holds its
        workspace; a workspace to prepare to its placement's pool, and one
        to release or purge to its host; station work to its lab. Any other
        kind keeps the lane it came with, the platform's own."""
        ...

    @abstractmethod
    async def admit(self, ctx: TenantContext, item: WorkItem) -> timedelta | None:
        """The guard a claimed loop meets before it runs: None when fewer of
        its tenant's loops run ahead of it than the tenant's share allows,
        and otherwise the delay it goes back to its lane for. The claim
        stays the guideline's, so the loops ahead are those claimed under a
        live lease before it in the claim order, and those claimed from any
        other lane. Every other kind is admitted."""
        ...

    @abstractmethod
    async def claim_for(
        self, rctx: RequestContext, claimant: Claimant, lease: timedelta
    ) -> tuple[TenantContext, WorkItem] | None:
        """Platform-internal: the claim the control plane makes on behalf of
        a host or a daemon outside its processes, which holds no database
        credential. The lanes and the kinds come from the claimant's
        identity, never from its call (`rules.claims_of`), and the claim
        carries its name. An item of another tenant than a claimant inside
        a tenant's wall is never handed over: it is failed for good, a dead
        letter, and the claim goes on. None when nothing is ready."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep's purge of a tenant deleted past its retention: its
        share goes; any other tenant costs nothing."""
        ...


class PlacementOperatorManagerInterface(ABC):
    """The operators' plane of placement: one named org's fair share. A
    tenant never writes its own, so none can raise its own limit."""

    @abstractmethod
    async def set_share(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        plan_tier: str,
        own_lane: bool,
        concurrency: int,
    ) -> FairShare:
        """Writes the org's share, its first or a new version of it, and
        leaves an audit event in the org's stream that names the operator.
        Its loops enqueued from then on go to the lane it names; a loop
        already queued stays in its lane. Requires the write permission.
        NotFound when the org is not there or is deleted; ValidationFailed
        when a field is out of its bounds."""
        ...
