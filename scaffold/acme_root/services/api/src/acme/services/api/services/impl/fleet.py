from uuid import UUID

from acme.om.context import OperatorContext
from acme.om.placement import PlacementOperatorManagerInterface
from acme.om.steps.types.header import (
    ControlHeader,
    LoopEndedHeader,
    ParkedHeader,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.trust import TrustOperatorManagerInterface
from acme.om.trust.types.shape import StepShape
from acme.services.api.services.fleet import FleetServiceInterface
from acme.services.api.services.impl.agent_sessions import park_view, step_view
from acme.services.api.types.agent_sessions import StepPageView
from acme.services.api.types.common import clamp_limit
from acme.services.api.types.fleet import (
    HostStandingView,
    LaneLoadView,
    LoopStandingView,
    SessionStandingView,
    SetShareRequest,
    ShapePageView,
    ShareView,
    StepShapeView,
)
from acme.services.api.types.hosts import AdvertisementView


def shape_view(shape: StepShape) -> StepShapeView:
    header = shape.header
    return StepShapeView(
        id=shape.id,
        seq=shape.seq,
        loop_id=shape.loop_id,
        type=shape.type,
        actor=shape.actor,
        origin=shape.origin,
        responds_to=shape.responds_to,
        created_at=shape.created_at,
        content=shape.content,
        tool=header.tool if isinstance(header, ToolRequestHeader) else None,
        failure=header.failure if isinstance(header, ToolResponseHeader) else None,
        command=header.command if isinstance(header, ControlHeader) else None,
        park=park_view(header.park) if isinstance(header, ParkedHeader) else None,
        outcome=header.outcome if isinstance(header, LoopEndedHeader) else None,
    )


class FleetServiceImpl(FleetServiceInterface):
    def __init__(
        self,
        placement: PlacementOperatorManagerInterface,
        trust: TrustOperatorManagerInterface,
    ) -> None:
        self._placement = placement
        self._trust = trust

    async def set_share(
        self, admin: OperatorContext, org_id: UUID, body: SetShareRequest
    ) -> ShareView:
        standing = await self._placement.set_share(
            admin,
            org_id,
            plan_tier=body.plan_tier,
            own_lane=body.own_lane,
            concurrency=body.concurrency,
        )
        share = standing.share
        return ShareView(
            org_id=org_id,
            plan_tier=share.plan_tier,
            own_lane=share.own_lane,
            concurrency=standing.concurrency,
            own_cap=standing.own_cap,
            version=share.version,
            updated_at=share.updated_at,
            updated_by=share.updated_by,
        )

    async def get_session_standing(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID
    ) -> SessionStandingView:
        standing = await self._placement.get_session_standing(admin, org_id, session_id)
        loop = standing.loop
        return SessionStandingView(
            session_id=standing.session_id,
            status=standing.status,
            park=park_view(standing.park),
            changed_at=standing.changed_at,
            pending_input=standing.pending_input,
            plan_tier=standing.plan_tier,
            own_lane=standing.own_lane,
            concurrency=standing.concurrency,
            own_cap=standing.own_cap,
            share_set=standing.share_set,
            pool_id=standing.pool_id,
            hosts_online=standing.hosts_online,
            loop=None if loop is None else LoopStandingView.model_validate(loop),
        )

    async def get_host_standing(
        self, admin: OperatorContext, org_id: UUID, host_id: UUID
    ) -> HostStandingView:
        standing = await self._placement.get_host_standing(admin, org_id, host_id)
        advertised = standing.advertisement
        return HostStandingView(
            host_id=standing.host_id,
            pool_id=standing.pool_id,
            state=standing.state,
            revoked=standing.revoked,
            advertisement=AdvertisementView(
                os=advertised.os,
                shell=advertised.shell,
                capabilities=list(advertised.capabilities),
                isolation_modes=list(advertised.isolation_modes),
            ),
            exec_version=standing.exec_version,
            exec_floor=standing.exec_floor,
            last_seen_at=standing.last_seen_at,
            lanes=[LaneLoadView.model_validate(load) for load in standing.lanes],
        )

    async def get_session_shape(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> ShapePageView:
        page = await self._trust.get_session_shape(
            admin, org_id, session_id, after_seq, clamp_limit(limit)
        )
        return ShapePageView(
            items=[shape_view(item) for item in page.items], has_more=page.has_more
        )

    async def get_session_content(
        self, admin: OperatorContext, org_id: UUID, session_id: UUID, after_seq: int, limit: int
    ) -> StepPageView:
        page = await self._trust.get_session_content(
            admin, org_id, session_id, after_seq, clamp_limit(limit)
        )
        return StepPageView(items=[step_view(step) for step in page.items], has_more=page.has_more)
