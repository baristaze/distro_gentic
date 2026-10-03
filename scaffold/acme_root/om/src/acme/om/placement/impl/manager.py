import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.observability import OUTCOMES
from acme.om.base import EMPTY_UUID, Platform, derived_id, utcnow
from acme.om.context import Permission, RequestContext, TenantContext
from acme.om.exceptions import LeaseLost, NotFound
from acme.om.placement.kinds import HOST, ClaimantKinds, claims_of, held_to, placed_lane
from acme.om.placement.manager import PlacementManagerInterface
from acme.om.placement.rules import DEFAULT_TIER, admits, loop_lane
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.types.claimant import Claimant, ClaimantReport, ReportOutcome
from acme.om.placement.types.share import FairShare
from acme.om.tenancy import TenancyManagerInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.kinds import WorkKinds
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

log = logging.getLogger(__name__)


class PlacementOptions(Platform):
    default_tier: str = DEFAULT_TIER  # the plan tier of a tenant with no share
    default_concurrency: int = 8  # the loops at once of a tenant with no share
    # How long a claimed loop over its tenant's share waits in its lane
    # before it is claimed again: long enough that a full tenant's queue is
    # not claimed over and over, short enough that a freed slot is taken.
    over_share_delay: timedelta = timedelta(seconds=15)
    purge_batch: int = 1000


class PlacementManagerImpl(PlacementManagerInterface):
    def __init__(
        self,
        storage: PlacementStorageInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        options: PlacementOptions,
        kinds: WorkKinds,
        claimants: ClaimantKinds,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        held_to(claimants, kinds)
        self._storage = storage
        self._work = work
        self._tenancy = tenancy
        self._options = options
        self._kinds = kinds
        self._claimants = claimants
        self._clock = clock

    async def lane_for(self, org_id: UUID, item: WorkItem) -> str:
        if item.kind == WorkKind.LOOP:
            return loop_lane(org_id, await self._share(org_id))
        return placed_lane(self._kinds.get(item.kind), item.payload) or item.lane

    async def admit(self, ctx: TenantContext, item: WorkItem) -> timedelta | None:
        if item.kind != WorkKind.LOOP:
            return None
        share = await self._share(ctx.org_id)
        ahead = await self._work.claimed_ahead(ctx, item)
        if admits(ahead, share.concurrency):
            return None
        OUTCOMES.labels(subsystem="placement", outcome="over_share").inc()
        log.info(
            "loop %s of org %s waits: %d of its loops run ahead of it, and its share is %d",
            item.id,
            ctx.org_id,
            ahead,
            share.concurrency,
        )
        return self._options.over_share_delay

    async def claim_for(
        self, rctx: RequestContext, claimant: Claimant, lease: timedelta
    ) -> tuple[TenantContext, WorkItem] | None:
        for lane, kinds in claims_of(self._claimants, self._kinds, claimant):
            while True:
                claimed = await self._work.claim(rctx, lane, kinds, claimant.worker_id, lease)
                if claimed is None:
                    break
                ctx, item = claimed
                if claimant.org_id is None or ctx.org_id == claimant.org_id:
                    return claimed
                # Routed into another tenant's wall: never handed over, and
                # never claimed again, since no claimant of that lane may
                # run it.
                OUTCOMES.labels(subsystem="placement", outcome="foreign_claim").inc()
                log.error(
                    "work item %s of org %s reached %s of org %s and is failed",
                    item.id,
                    ctx.org_id,
                    claimant.worker_id,
                    claimant.org_id,
                )
                await self._work.fail_for_good(
                    ctx, item, f"routed to {claimant.worker_id} of another tenant"
                )
        return None

    async def report_for(
        self, rctx: RequestContext, claimant: Claimant, org_id: UUID, report: ClaimantReport
    ) -> WorkItem:
        ctx, item = await self._held(rctx, claimant, org_id, report.item_id, report.claim_token)
        if report.outcome is ReportOutcome.DONE:
            return await self._work.complete(ctx, item)
        assert report.error is not None  # the report's own rule
        return await self._work.fail(ctx, item, f"{claimant.worker_id}: {report.error}")

    async def extend_for(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        claim_token: UUID,
        lease: timedelta,
    ) -> WorkItem:
        ctx, item = await self._held(rctx, claimant, org_id, item_id, claim_token)
        return await self._work.extend_lease(ctx, item, lease)

    async def held_for(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        claim_token: UUID,
    ) -> WorkItem:
        return (await self._held(rctx, claimant, org_id, item_id, claim_token))[1]

    async def _held(
        self,
        rctx: RequestContext,
        claimant: Claimant,
        org_id: UUID,
        item_id: UUID,
        claim_token: UUID,
    ) -> tuple[TenantContext, WorkItem]:
        """The item the claimant holds, under its tenant's service context.
        One of another tenant, held by another claimant, of a kind its kind
        does not take, or not there at all is the same NotFound, so a
        claimant learns nothing of work that is not its own. Its own item
        under a token that is not the claim's, since its lease lapsed and
        the item was claimed again, is LeaseLost: the claim token, not the
        claimant's name, is the fence. A host reads and answers its items
        through the relay, which keeps their record, so it holds none here."""
        missing = NotFound(f"{claimant.worker_id} holds no work item {item_id}")
        if claimant.kind == HOST or (claimant.org_id is not None and org_id != claimant.org_id):
            raise missing
        ctx = await self._tenancy.service_context(rctx, org_id, EMPTY_UUID)
        try:
            item = await self._work.get_item(ctx, item_id)
        except NotFound:
            raise missing from None
        if (
            item.status is not WorkStatus.CLAIMED
            or item.claimed_by != claimant.worker_id
            or item.kind not in self._kinds.claimed_by(claimant.kind)
        ):
            raise missing
        if item.claim_token != claim_token:
            raise LeaseLost(f"{claimant.worker_id} no longer holds work item {item_id}")
        return ctx, item

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    async def _share(self, org_id: UUID) -> FairShare:
        """The tenant's share, or the default one when no operator wrote it."""
        stored = await self._storage.read_share(org_id)
        if stored is not None:
            return stored
        now = self._clock()
        return FairShare(
            id=derived_id(org_id, now),
            created_at=now,
            updated_at=now,
            created_by=EMPTY_UUID,  # the platform's default, which nobody wrote
            updated_by=EMPTY_UUID,
            plan_tier=self._options.default_tier,
            concurrency=self._options.default_concurrency,
        )
