import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from acme.infra.topics import EntityChangedPayload, Topics, TopicsInterface
from acme.om.base import new_id, utcnow
from acme.om.context import OperatorContext, OperatorPermission
from acme.om.events.storage import EventStorageInterface
from acme.om.events.types.event import Event
from acme.om.exceptions import NotFound, PreconditionFailed, UniqueKeyTaken, ValidationFailed
from acme.om.placement.manager import PlacementOperatorManagerInterface
from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.types.share import FairShare
from acme.om.tenancy.storage import TenancyStorageInterface

log = logging.getLogger(__name__)

SHARE_SET_KIND = "placement.share.set"
"""The audit event an operator's write of a share leaves in the tenant's stream."""


class PlacementOperatorManagerImpl(PlacementOperatorManagerInterface):
    """Writes one named org's share through the placement storage and reads
    the org through the tenancy storage, as the other operator planes do:
    no `TenantContext` exists on this plane, so no tenant manager is asked."""

    def __init__(
        self,
        storage: PlacementStorageInterface,
        tenancy: TenancyStorageInterface,
        events: EventStorageInterface,
        topics: TopicsInterface,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._tenancy = tenancy
        self._events = events
        self._topics = topics
        self._clock = clock

    async def set_share(
        self,
        admin: OperatorContext,
        org_id: UUID,
        *,
        plan_tier: str,
        own_lane: bool,
        concurrency: int,
    ) -> FairShare:
        admin.require(OperatorPermission.WRITE)
        org = await self._tenancy.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        stored = await self._storage.read_share(org_id)
        now = self._clock()
        terms = {"plan_tier": plan_tier, "own_lane": own_lane, "concurrency": concurrency}
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
            "operator %s set the share of org %s: tier %s, own lane %s, %d at once",
            admin.identity_id,
            org_id,
            share.plan_tier,
            share.own_lane,
            share.concurrency,
        )
        await self._audit(admin, org_id, share)
        return share

    async def _audit(self, admin: OperatorContext, org_id: UUID, share: FairShare) -> None:
        """The event that names the write and who made it, with the terms it
        set. The share lands first and the stream after, as the queue's
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
                        "concurrency": share.concurrency,
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
