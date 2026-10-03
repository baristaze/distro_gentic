"""The placement swimlane: where each kind of a session's work runs, the
claim the control plane makes for a host, and each tenant's fair share of
the loops, held at the claim."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from acme.om.context import OperatorContext, RequestContext, TenantContext
from acme.om.placement.types.claimant import Claimant, ClaimantReport
from acme.om.placement.types.share import FairShare

if TYPE_CHECKING:
    # The work queue fixes its payloads by kind, and the payloads of the
    # kinds a host runs are this namespace's, so the work item
    # is named here for the type checker alone.
    from acme.om.placement.types.standing import FleetCounts, HostStanding, SessionStanding
    from acme.om.work.types.work_item import WorkItem


class PlacementManagerInterface(ABC):
    @abstractmethod
    async def lane_for(self, org_id: UUID, item: WorkItem) -> str:
        """Platform-internal: the lane an item is enqueued on, which the work
        manager asks at every enqueue, so no producer picks one. A loop goes
        to its tenant's lane, a lane of its own when its share says so and
        its plan tier's otherwise. A kind with a lane of its own goes where
        its registered lane reads off its payload: a command to the host
        that holds its workspace, a workspace to prepare to its placement's
        pool and one to release or purge to its host, and a product's kind
        where its own lane says. Any other kind keeps the lane it came with,
        the platform's own."""
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
        a claimant outside its processes, which holds no database
        credential. The lanes and the kinds come from the claimant's
        identity, never from its call (`kinds.claims_of`): only the kinds
        registered for its claimant kind, and the claim carries its name.
        An item of another tenant than a claimant inside a tenant's wall is
        never handed over: it is failed for good, a dead letter, and the
        claim goes on. None when nothing is ready."""
        ...

    @abstractmethod
    async def held_for(
        self, rctx: RequestContext, claimant: Claimant, org_id: UUID, item_id: UUID
    ) -> WorkItem:
        """Platform-internal: the item `claimant` holds, in the tenant
        `org_id`, as the gateway reads it for the claimant. NotFound alike
        for an item of another tenant, one another claimant holds, one of a
        kind its kind does not take, and one not there, so a claimant reads
        only the items it holds, within its tenant."""
        ...

    @abstractmethod
    async def report_for(
        self, rctx: RequestContext, claimant: Claimant, org_id: UUID, report: ClaimantReport
    ) -> WorkItem:
        """Platform-internal: a claimant's answer for an item it holds, as
        the gateway passes it: done completes the item, failed fails it with
        the reason, retried until its attempts are spent. Held as `held_for`
        holds the read, and LeaseLost once its claim went to another."""
        ...

    @abstractmethod
    async def extend_for(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        lease: timedelta,
    ) -> WorkItem:
        """Platform-internal: renews the lease on an item the claimant holds,
        held as `held_for` holds the read."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep's purge of a tenant deleted past its retention: its
        share goes; any other tenant costs nothing."""
        ...


class PlacementOperatorManagerInterface(ABC):
    """The operators' plane of placement: one named org's fair share, which
    a tenant never writes, so none can raise its own limit; where one of its
    sessions' work stands, and what one of its hosts is handed. Each read
    names the tenant and is logged with the operator, and answers ids,
    counts, times, and states, never what the tenant wrote."""

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

    @abstractmethod
    async def get_session_standing(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID
    ) -> SessionStanding:
        """Why the named tenant's session is or is not moving: its status, its
        park and when it last changed, its tenant's share, where it runs and
        how many of its pool's hosts are online, and its loop item made last
        with its place in line. Requires the read permission. NotFound for a
        session the tenant does not hold."""
        ...

    @abstractmethod
    async def get_host_standing(
        self, admin: OperatorContext, org_id: UUID, host_id: UUID
    ) -> HostStanding:
        """Why the named tenant's host takes no work: its state, what it
        advertised, the version of `exec` work it reads against the floor,
        when it last called, and the ready items, by kind, on its pool's lane
        and its own. Requires the read permission. NotFound for a host the
        tenant does not hold."""
        ...

    @abstractmethod
    async def fleet_counts(self) -> FleetCounts:
        """Platform-internal: the sweep's read of the platform's signals,
        across every tenant, each by bounded labels alone: the parked
        sessions by park reason and age, the ready loops by plan tier (every
        tenant's own lane under one label), and the hosts by state. Takes no
        context, because it reads for no tenant and no principal."""
        ...
