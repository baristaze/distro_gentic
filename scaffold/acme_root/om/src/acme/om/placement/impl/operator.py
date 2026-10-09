import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from acme.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import OperatorContext, OperatorPermission
from acme.om.events.storage import EventStorageInterface
from acme.om.events.types.event import Event
from acme.om.exceptions import NotFound, PreconditionFailed, UniqueKeyTaken, ValidationFailed
from acme.om.hosts.rules import WIRE_FLOOR, HostState, WireType, host_state, online
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.placement.manager import PlacementOperatorManagerInterface
from acme.om.placement.rules import (
    LOOP_LANE_PREFIX,
    PARK_AGES,
    host_lane,
    lane_cap,
    loop_lane,
    own_lane,
    park_age_label,
    pool_lane,
    tier_label,
    tier_lane,
)
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.types.share import FairShare, ShareStanding, TierShare
from acme.om.placement.types.standing import (
    Count,
    FleetCounts,
    HostStanding,
    LaneLoad,
    LoopStanding,
    SessionStanding,
)
from acme.om.steps.types.header import ParkReason
from acme.om.tenancy.storage import TenancyStorageInterface
from acme.om.work.manager import WorkOperatorManagerInterface
from acme.om.work.storage import WorkStorageInterface
from acme.om.work.types.tenant_cap import MAX_CAP, TenantCap
from acme.om.work.types.work_item import WorkKind

log = logging.getLogger(__name__)

SHARE_SET_KIND = "placement.share.set"
"""The audit event an operator's write of a share leaves in the tenant's stream."""


class PlacementOperatorOptions(Platform):
    """What a standing reads beside the rows: the tier of a tenant no
    operator gave a share, and each tier's share, as placement's options
    set them, and how long a host counts as online, as the hosts' options
    set it. The root builds it from both, so neither is said twice."""

    default_tier: str
    tier_shares: tuple[TierShare, ...]
    default_share: int
    online_window: timedelta


class PlacementOperatorManagerImpl(PlacementOperatorManagerInterface):
    """Writes one named org's share through the placement storage, and its
    own cap through the work queue's operator plane, which holds the cap
    and its trail. It reads the org, its sessions, its work, and its hosts
    through their storages, as the other operator planes do: no
    `TenantContext` exists on this plane, so no tenant manager is asked."""

    def __init__(
        self,
        storage: PlacementStorageInterface,
        tenancy: TenancyStorageInterface,
        events: EventStorageInterface,
        topics: TopicsInterface,
        sessions: AgentSessionStorageInterface,
        work: WorkStorageInterface,
        hosts: HostsStorageInterface,
        work_operator: WorkOperatorManagerInterface,
        options: PlacementOperatorOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._events = events
        self._topics = topics
        self._sessions = sessions
        self._work = work
        self._hosts = hosts
        self._work_operator = work_operator
        self._options = options
        self._clock = clock

    async def set_share(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        plan_tier: str,
        own_lane: bool,
        concurrency: int | None = None,
    ) -> ShareStanding:
        admin.require(OperatorPermission.WRITE)
        org = await self._tenancy.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        stored = await self._storage.read_share(org_id)
        now = self._clock()
        terms = {"plan_tier": plan_tier, "own_lane": own_lane}
        # An operator has no user in the tenant: the identity is the actor.
        try:
            if stored is None:
                share = FairShare.model_validate(
                    {
                        "id": new_id(),
                        "created_at": now,
                        "updated_at": now,
                        "created_by": admin.identity_id,
                        "updated_by": admin.identity_id,
                        **terms,
                    }
                )
            else:
                share = FairShare.model_validate(
                    {
                        **stored.model_dump(),
                        **terms,
                        "version": stored.version + 1,
                        "updated_at": now,
                        "updated_by": admin.identity_id,
                    }
                )
        except ValidationError as error:
            raise ValidationFailed(f"fair share of org {org_id}: {error}"[:500]) from None
        if concurrency is not None and not 1 <= concurrency <= MAX_CAP:
            raise ValidationFailed(f"fair share of org {org_id}: a cap is 1 to {MAX_CAP}")
        lane = loop_lane(org_id, share)
        # The cap lands before the share: a failure between leaves a cap on
        # a lane the org's loops do not reach yet, and the operator's retry
        # writes both. Only the lane the share names is written: a cap on a
        # lane the org leaves stays, since its loops queued there stay too,
        # and a move back writes it again.
        if concurrency is None:
            await self._clear_cap(admin, org_id, lane)
        else:
            await self._work_operator.set_tenant_cap(admin, org_id, lane, concurrency)
        if stored is None:
            try:
                landed = await self._storage.create_share(org_id, share)
            except UniqueKeyTaken as error:
                raise PreconditionFailed("the org's share was written meanwhile") from error
            if not landed:
                raise PreconditionFailed(f"fair share {share.id} is written already")
        else:
            await self._storage.write_share(org_id, share, stored.version)
        log.info(
            "operator %s set the share of org %s: tier %s, own lane %s, its own cap %s",
            admin.identity_id,
            org_id,
            share.plan_tier,
            share.own_lane,
            concurrency,
        )
        await self._audit(admin, org_id, share, concurrency)
        return ShareStanding(
            share=share,
            concurrency=self._lane_cap(lane) if concurrency is None else concurrency,
            own_cap=concurrency is not None,
        )

    async def get_session_standing(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID
    ) -> SessionStanding:
        admin.require(OperatorPermission.READ)
        session = await self._sessions.read_session(org_id, session_id)
        if session is None:
            raise NotFound(f"agent session {session_id} is not in {org_id}")
        self._trail(admin, org_id, "a session's standing")
        now = self._clock()
        stored = await self._storage.read_share(org_id)
        tier = self._options.default_tier if stored is None else stored.plan_tier
        moved = stored is not None and stored.own_lane
        item = await self._work.read_latest_for_target(org_id, WorkKind.LOOP, session_id)
        # The cap of the lane the loop stands on, which a move leaves where
        # it is; with no loop, of the lane its next one goes to.
        if item is not None:
            lane = item.lane
        else:
            lane = own_lane(org_id) if moved else tier_lane(tier)
        own = await self._work.read_tenant_cap(org_id, lane)
        placement = await self._hosts.read_placement(org_id, session_id)
        pool_id = None if placement is None else placement.pool_id
        hosts_online = None
        if pool_id is not None:
            hosts = await self._hosts.read_hosts(org_id, pool_id, 1000)
            hosts_online = sum(
                1 for host in hosts if online(host, now, self._options.online_window)
            )
        loop = None
        if item is not None:
            loop = LoopStanding(
                item_id=item.id,
                status=item.status,
                lane=item.lane,
                attempts=item.attempts,
                max_attempts=item.max_attempts,
                available_at=item.available_at,
                claimed_by=item.claimed_by,
                lease_expires_at=item.lease_expires_at,
                ready_ahead=await self._work.count_ready_ahead(item, now),
                running_ahead=await self._work.count_claimed_ahead(org_id, item, now),
            )
        return SessionStanding(
            session_id=session.id,
            status=session.status,
            park=session.park,
            changed_at=session.updated_at,
            pending_input=session.pending_input is not None,
            plan_tier=tier,
            own_lane=moved,
            concurrency=self._lane_cap(lane) if own is None else own.cap,
            own_cap=own is not None,
            share_set=stored is not None,
            pool_id=pool_id,
            hosts_online=hosts_online,
            loop=loop,
        )

    async def get_host_standing(
        self, admin: OperatorContext, org_id: UUID, host_id: UUID
    ) -> HostStanding:
        admin.require(OperatorPermission.READ)
        host = await self._hosts.read_host(org_id, host_id)
        if host is None:
            raise NotFound(f"host {host_id} is not in {org_id}")
        self._trail(admin, org_id, "a host's standing")
        now = self._clock()
        lanes = (pool_lane(host.pool_id), host_lane(host.id))
        ready = await self._work.count_ready_on_lanes(org_id, lanes, now)
        floor = WIRE_FLOOR[WireType.EXEC]
        return HostStanding(
            host_id=host.id,
            pool_id=host.pool_id,
            state=host_state(
                host.last_seen_at > now - self._options.online_window, host.exec_version >= floor
            ),
            revoked=host.revoked_at is not None,
            advertisement=host.advertisement,
            exec_version=host.exec_version,
            exec_floor=floor,
            last_seen_at=host.last_seen_at,
            lanes=tuple(
                LaneLoad(lane=lane, kind=kind, ready=count)
                for (lane, kind), count in sorted(ready.items())
            ),
        )

    async def fleet_counts(self) -> FleetCounts:
        now = self._clock()
        parked = await self._sessions.count_parked(tuple(now - cut for _, cut in PARK_AGES))
        ages = range(len(PARK_AGES) + 1)
        depth: dict[str, int] = {}
        for lane, count in (await self._work.count_ready_by_lane(LOOP_LANE_PREFIX, now)).items():
            label = tier_label(lane)
            if label is not None:
                depth[label] = depth.get(label, 0) + count
        hosts: dict[HostState, int] = dict.fromkeys(HostState, 0)
        seen_since = now - self._options.online_window
        for (seen, at_floor), count in (
            await self._hosts.count_hosts(seen_since, WIRE_FLOOR[WireType.EXEC])
        ).items():
            hosts[host_state(seen, at_floor)] += count
        # Every reason and age is a series, zero included, so a park that
        # ends reads as a fall to zero and never as a line that stops.
        return FleetCounts(
            parked=tuple(
                Count(
                    labels=(reason.value, park_age_label(age)),
                    value=parked.get((reason, age), 0),
                )
                for reason in ParkReason
                for age in ages
            ),
            loops_ready=tuple(
                Count(labels=(label,), value=count) for label, count in sorted(depth.items())
            ),
            hosts=tuple(Count(labels=(state.value,), value=n) for state, n in hosts.items()),
        )

    async def carry_caps(self, limit: int) -> int:
        carried = 0
        for row in await self._storage.read_uncarried(limit):
            lane = loop_lane(row.org_id, row.share)
            if await self._work.read_tenant_cap(row.org_id, lane) is None:
                now = self._clock()
                cap = TenantCap(
                    id=new_id(),
                    created_at=now,
                    updated_at=now,
                    # The operator who wrote the share set the number.
                    created_by=row.share.updated_by,
                    updated_by=row.share.updated_by,
                    lane=lane,
                    cap=max(1, min(row.concurrency, MAX_CAP)),
                )
                await self._work.write_tenant_cap(row.org_id, cap)
                log.info(
                    "carried the share of org %s as its own cap on lane %s: %d",
                    row.org_id,
                    lane,
                    cap.cap,
                )
            if await self._storage.mark_carried(row.org_id, row.share.id):
                carried += 1
        return carried

    def _lane_cap(self, lane: str) -> int:
        return lane_cap(lane, self._options.tier_shares, self._options.default_share)

    async def _clear_cap(self, admin: OperatorContext, org_id: UUID, lane: str) -> None:
        """The org's own cap off the lane, so the lane's holds; none there
        is already so."""
        with suppress(NotFound):
            await self._work_operator.clear_tenant_cap(admin, org_id, lane)

    @staticmethod
    def _trail(admin: OperatorContext, org_id: UUID, what: str) -> None:
        """Every operator read of a tenant's rows is recorded, naming both."""
        log.info(
            "operator read of %s",
            what,
            extra={"org_id": str(org_id), "operator": str(admin.identity_id)},
        )

    async def _audit(
        self, admin: OperatorContext, org_id: UUID, share: FairShare, concurrency: int | None
    ) -> None:
        """The event that names the write and who made it, with the terms it
        set: `concurrency` is the org's own cap, null where its lane's
        holds. The share lands first and the stream after, as the queue's
        operator requeue does: a crash between the two loses the entry,
        never the share."""
        (event,) = await self._events.append_events(
            org_id,
            [
                Event(
                    id=new_id(),
                    org_id=org_id,
                    kind=SHARE_SET_KIND,
                    target_id=share.id,
                    payload={
                        "plan_tier": share.plan_tier,
                        "own_lane": share.own_lane,
                        "concurrency": concurrency,
                        "version": share.version,
                    },
                    produced_at=self._clock(),
                    actor_id=admin.identity_id,
                    request_id=admin.request_id,
                    app=admin.app.type.value,
                ),
            ],
        )
        await self._topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=event.id,
                produced_at=event.produced_at,
                org_id=org_id,
                kind=event.kind,
                target_id=event.target_id,
                seq=event.seq,
                actor_id=event.actor_id,
            ),
        )
