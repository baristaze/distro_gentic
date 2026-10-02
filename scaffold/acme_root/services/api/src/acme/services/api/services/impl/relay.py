import asyncio
import base64
import binascii
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.topics import (
    EntityChangedPayload,
    TopicPayload,
    Topics,
    TopicsInterface,
    WorkAvailablePayload,
)
from acme.om.base import utcnow
from acme.om.context import RequestContext
from acme.om.exceptions import ValidationFailed
from acme.om.hosts.types.host import HostIdentity
from acme.om.placement.rules import host_lane, pool_lane
from acme.om.relay import RelayManagerInterface
from acme.om.relay.rules import CONTROL_KIND
from acme.om.relay.types.exec import REQUESTS
from acme.om.retention.crossing import Crossing
from acme.services.api.services.relay import RelayServiceInterface
from acme.services.api.types.relay import (
    ControlKind,
    ControlView,
    CrossingBody,
    ExecDetailView,
    LeaseView,
    PartRequest,
    ResultRequest,
)

log = logging.getLogger(__name__)

STREAM_SPAN = timedelta(seconds=60)
"""How long one control stream lives. It ends then, and its host opens the
next with the credential it holds at that moment."""


def decoded(data: str) -> bytes:
    """The bytes a body carries in base64, exactly as they crossed."""
    try:
        return base64.b64decode(data, validate=True)
    except binascii.Error:
        raise ValidationFailed("data is base64") from None


def crossing_of(body: CrossingBody) -> Crossing:
    return Crossing(kind=body.kind, sha256=body.sha256, size=body.size)


class RelayServiceImpl(RelayServiceInterface):
    """`poll` is how long the control stream waits for a wake before it
    reads the host's control messages again and pings."""

    def __init__(
        self,
        relay: RelayManagerInterface,
        topics: TopicsInterface,
        *,
        poll: timedelta = timedelta(seconds=5),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._relay = relay
        self._topics = topics
        self._poll = poll
        self._clock = clock

    async def detail(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID
    ) -> ExecDetailView:
        detail = await self._relay.detail(rctx, host, item_id)
        return ExecDetailView(
            item_id=detail.item_id,
            call_id=detail.key,
            org_id=detail.org_id,
            session_id=detail.session_id,
            effect=detail.effect,
            deadline=detail.deadline,
            epoch=detail.epoch,
            spec=detail.spec.model_dump(mode="json"),
            location=detail.location,
            request=REQUESTS.dump_python(detail.request, mode="json"),
        )

    async def push_part(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: PartRequest
    ) -> None:
        await self._relay.push_part(
            rctx,
            host,
            item_id,
            body.seq,
            body.stream.value,
            crossing_of(body.crossing),
            decoded(body.data),
        )

    async def push_result(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: ResultRequest
    ) -> None:
        await self._relay.push_result(
            rctx, host, item_id, crossing_of(body.crossing), decoded(body.data)
        )

    async def extend(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> LeaseView:
        return LeaseView(lease_expires_at=await self._relay.extend(rctx, host, item_id))

    async def control(
        self, rctx: RequestContext, host: HostIdentity, after: UUID | None
    ) -> AsyncIterator[ControlView]:
        woken = asyncio.Event()
        work: list[bool] = []
        lanes = {host_lane(host.host_id), pool_lane(host.pool_id)}

        async def on_work(payload: TopicPayload) -> None:
            if isinstance(payload, WorkAvailablePayload) and payload.lane in lanes:
                work.append(True)
                woken.set()

        async def on_change(payload: TopicPayload) -> None:
            if (
                isinstance(payload, EntityChangedPayload)
                and payload.org_id == host.org_id
                and payload.kind == CONTROL_KIND
            ):
                woken.set()

        consumer = f"host-control:{host.host_id}"
        unsubscribes = [
            self._topics.subscribe(Topics.WORK_AVAILABLE, consumer, on_work),
            self._topics.subscribe(Topics.ENTITY_CHANGED, consumer, on_change),
        ]
        try:
            # A host that opens its stream claims at once: a wake it missed
            # while it was away is not lost.
            yield ControlView(kind=ControlKind.WAKE)
            last = after
            opened = self._clock()
            while True:
                for control in await self._relay.controls(rctx, host, last):
                    last = control.id
                    yield ControlView(
                        kind=ControlKind(control.kind.value), id=control.id, item_id=control.item_id
                    )
                if work:
                    work.clear()
                    yield ControlView(kind=ControlKind.WAKE)
                now = self._clock()
                if now >= host.expires_at or now - opened >= STREAM_SPAN:
                    # It ends, and the host opens the next with the credential
                    # it holds then, which the gateway checks as it checks
                    # every call. Nothing here shows a credential again: one
                    # the host rotated meanwhile is never presented as reused.
                    return
                wait = min(self._poll, opened + STREAM_SPAN - now)
                try:
                    await asyncio.wait_for(woken.wait(), wait.total_seconds())
                except TimeoutError:
                    yield ControlView(kind=ControlKind.PING)
                woken.clear()
        finally:
            for unsubscribe in unsubscribes:
                unsubscribe()
