import asyncio
import base64
import binascii
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
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
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.exec_relay.rules import CONTROL_KIND
from acme.om.exec_relay.types.exec import REQUESTS, PrepareAnswer, SentPart, SnapshotAnswer
from acme.om.hosts.types.host import HostIdentity
from acme.om.placement.rules import host_lane, pool_lane
from acme.om.retention.crossing import Crossing
from acme.services.api.services.exec_relay import ExecRelayServiceInterface
from acme.services.api.types.exec_relay import (
    ControlKind,
    ControlView,
    CrossingBody,
    ExecDetailView,
    ExecLeaseView,
    IssuedObjectPartView,
    IssuedObjectUploadView,
    ObjectRefView,
    ObjectSlotView,
    PartRequest,
    PartsRequest,
    PreparedView,
    PrepareRequest,
    ResultRequest,
    SnapshotRequest,
    UploadRequest,
)

log = logging.getLogger(__name__)

STREAM_SPAN = timedelta(seconds=60)
"""The longest one control stream lives. It ends then, and its host opens
the next with the credential it holds at that moment."""

SPAN_JITTER = 0.25
"""The share of `STREAM_SPAN` a stream may end early by, drawn as it opens,
so streams opened together do not all end, and open again, together."""


def decoded(data: str) -> bytes:
    """The bytes a body carries in base64, exactly as they crossed."""
    try:
        return base64.b64decode(data, validate=True)
    except binascii.Error:
        raise ValidationFailed("data is base64") from None


def crossing_of(body: CrossingBody) -> Crossing:
    return Crossing(kind=body.kind, sha256=body.sha256, size=body.size)


class ExecRelayServiceImpl(ExecRelayServiceInterface):
    """`poll` is how long the control stream waits for a wake before it
    reads the host's control messages again and pings. `spacing` is the
    least time between two of its reads, however many wakes come: the wakes
    within it are answered by one read."""

    def __init__(
        self,
        relay: ExecRelayManagerInterface,
        topics: TopicsInterface,
        *,
        poll: timedelta = timedelta(seconds=5),
        spacing: timedelta = timedelta(seconds=1),
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._relay = relay
        self._topics = topics
        self._poll = poll
        self._spacing = spacing
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter

    async def detail(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID
    ) -> ExecDetailView:
        detail = await self._relay.detail(rctx, host, item_id)
        return ExecDetailView(
            item_id=detail.item_id,
            call_id=detail.key,
            org_id=detail.org_id,
            agent_session_id=detail.agent_session_id,
            effect=detail.effect,
            deadline=detail.deadline,
            epoch=detail.epoch,
            spec=detail.spec.model_dump(mode="json"),
            location=detail.location,
            request=REQUESTS.dump_python(detail.request, mode="json"),
            output=None
            if detail.output is None
            else ObjectSlotView(reference=detail.output.reference, key=detail.output.key),
            file_in=None
            if detail.file_in is None
            else ObjectRefView.model_validate(detail.file_in.model_dump()),
            file_out=None
            if detail.file_out is None
            else ObjectSlotView(reference=detail.file_out.reference, key=detail.file_out.key),
            url=detail.url,
            url_expires_at=detail.url_expires_at,
        )

    async def issue_upload(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: UploadRequest
    ) -> IssuedObjectUploadView:
        issued = await self._relay.issue_upload(rctx, host, item_id, body.object, body.size_bytes)
        return IssuedObjectUploadView(
            parts=[IssuedObjectPartView.model_validate(part.model_dump()) for part in issued.parts],
            remaining=issued.remaining,
            expires_at=issued.expires_at,
        )

    async def push_parts(
        self,
        rctx: RequestContext,
        host: HostIdentity,
        item_id: UUID,
        body: PartsRequest | PartRequest,
    ) -> None:
        pushed = body.parts if isinstance(body, PartsRequest) else [body]
        parts = [
            SentPart(
                seq=part.seq,
                stream=part.stream.value,
                crossing=crossing_of(part.crossing),
                data=decoded(part.data),
            )
            for part in pushed
        ]
        await self._relay.push_parts(rctx, host, item_id, parts)

    async def push_result(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: ResultRequest
    ) -> None:
        await self._relay.push_result(
            rctx, host, item_id, crossing_of(body.crossing), decoded(body.data)
        )

    async def prepared(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: PrepareRequest
    ) -> PreparedView:
        try:
            answer = PrepareAnswer(
                location=body.location,
                refused=body.refused,
                lost=body.lost,
                unbuilt=body.unbuilt,
            )
        except ValueError as error:
            raise ValidationFailed(
                "a prepare is answered with its location or its refusal, and only a refusal is "
                "lost or unbuilt, never both"
            ) from error
        binding = await self._relay.prepared(rctx, host, item_id, answer)
        return PreparedView(held=binding is not None and binding.host_id == host.host_id)

    async def released(self, rctx: RequestContext, host: HostIdentity, item_id: UUID) -> None:
        await self._relay.released(rctx, host, item_id)

    async def snapshotted(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID, body: SnapshotRequest
    ) -> None:
        try:
            answer = SnapshotAnswer(
                reference=body.reference, digest=body.digest, size=body.size, refused=body.refused
            )
        except ValueError as error:
            raise ValidationFailed(
                "a snapshot is answered as kept, with its reference, digest, and size, or as "
                "refused"
            ) from error
        await self._relay.snapshotted(rctx, host, item_id, answer)

    async def extend(
        self, rctx: RequestContext, host: HostIdentity, item_id: UUID
    ) -> ExecLeaseView:
        return ExecLeaseView(lease_expires_at=await self._relay.extend(rctx, host, item_id))

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
            span = STREAM_SPAN * (1 - SPAN_JITTER * self._jitter())
            while True:
                read = self._clock()
                for control in await self._relay.controls(rctx, host, last):
                    last = control.id
                    yield ControlView(
                        kind=ControlKind(control.kind.value), id=control.id, item_id=control.item_id
                    )
                if work:
                    work.clear()
                    yield ControlView(kind=ControlKind.WAKE)
                now = self._clock()
                if now >= host.expires_at or now - opened >= span:
                    # It ends, and the host opens the next with the credential
                    # it holds then, which the gateway checks as it checks
                    # every call. Nothing here shows a credential again: one
                    # the host rotated meanwhile is never presented as reused.
                    return
                wait = min(self._poll, opened + span - now)
                try:
                    await asyncio.wait_for(woken.wait(), wait.total_seconds())
                except TimeoutError:
                    yield ControlView(kind=ControlKind.PING)
                # A burst of wakes is one read, not a read each.
                rest = read + self._spacing - self._clock()
                if rest > timedelta(0):
                    await self._sleep(rest.total_seconds())
                woken.clear()
        finally:
            for unsubscribe in unsubscribes:
                unsubscribe()
