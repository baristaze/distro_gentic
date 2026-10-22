import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.topics import (
    StreamAppendedPayload,
    TopicPayload,
    Topics,
    TopicsInterface,
    WorkAvailablePayload,
)
from acme.om.base import thaw_mapping, utcnow
from acme.om.cloud_pool import CloudPoolManagerInterface
from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import CredentialExpired
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.rules import WIRE_VERSION, WireType, at_or_above_floor
from acme.om.hosts.types.credential import EnrollmentToken, IssuedCredential
from acme.om.hosts.types.host import (
    Advertisement,
    ClaimantEnrollment,
    ClaimantIdentity,
    EnrolledClaimant,
    Enrollment,
    Host,
    HostIdentity,
    HostReport,
    HostStatus,
)
from acme.om.hosts.types.pool import HostPool
from acme.om.work.types.work_item import WorkItem
from acme.services.api.services.hosts import HostsServiceInterface
from acme.services.api.services.impl.exec_relay import SPAN_JITTER, STREAM_SPAN
from acme.services.api.types.hosts import (
    AdvertisementBody,
    AdvertisementView,
    ClaimantClaimView,
    ClaimantControlKind,
    ClaimantControlView,
    ClaimantEnrollRequest,
    ClaimantReportRequest,
    ClaimantView,
    ClaimantWorkView,
    ClaimedWorkView,
    ClaimRequest,
    ClaimView,
    CreatePoolRequest,
    EnrollmentTokenView,
    EnrollRequest,
    ExtendLeaseRequest,
    HeartbeatRequest,
    HostView,
    IssuedClaimantCredentialView,
    IssuedEnrollmentTokenView,
    IssuedHostCredentialView,
    IssueEnrollmentTokenRequest,
    PlaceAgentSessionRequest,
    PlacementView,
    PoolView,
)


def pool_view(pool: HostPool) -> PoolView:
    return PoolView(
        id=pool.id,
        name=pool.name,
        region=pool.region,
        labels=list(pool.labels),
        created_at=pool.created_at,
        created_by=pool.created_by,
    )


def token_view(token: EnrollmentToken) -> EnrollmentTokenView:
    return EnrollmentTokenView.model_validate(token)


def host_view(host: Host, online: bool) -> HostView:
    advertised = host.advertisement
    return HostView(
        id=host.id,
        pool_id=host.pool_id,
        name=host.name,
        advertisement=AdvertisementView(
            os=advertised.os,
            shell=advertised.shell,
            capabilities=list(advertised.capabilities),
            isolation_modes=list(advertised.isolation_modes),
        ),
        exec_version=host.exec_version,
        last_seen_at=host.last_seen_at,
        online=online,
        revoked_at=host.revoked_at,
        created_at=host.created_at,
    )


def status_view(status: HostStatus) -> HostView:
    return host_view(status.host, status.online)


def advertisement(body: AdvertisementBody) -> Advertisement:
    return Advertisement(
        os=body.os,
        shell=body.shell,
        capabilities=tuple(body.capabilities),
        isolation_modes=tuple(body.isolation_modes),
    )


def credential_view(issued: IssuedCredential) -> IssuedHostCredentialView:
    return IssuedHostCredentialView(
        token=issued.credential,
        credential_id=issued.credential_id,
        host_id=issued.claimant_id,
        pool_id=issued.pool_id,
        expires_at=issued.expires_at,
    )


def claimant_credential_view(issued: IssuedCredential) -> IssuedClaimantCredentialView:
    return IssuedClaimantCredentialView(
        token=issued.credential,
        credential_id=issued.credential_id,
        kind=issued.kind,
        claimant_id=issued.claimant_id,
        pool_id=issued.pool_id,
        expires_at=issued.expires_at,
    )


def claimant_view(claimant: EnrolledClaimant) -> ClaimantView:
    return ClaimantView.model_validate(claimant)


def work_view(org_id: UUID, item: WorkItem) -> ClaimantWorkView:
    """An item a claimant holds, in its own tenant."""
    return ClaimantWorkView(
        id=item.id,
        org_id=org_id,
        kind=item.kind,
        status=item.status,
        target_id=item.target_id,
        payload=thaw_mapping(item.payload),
        lease_expires_at=item.lease_expires_at,
        attempts=item.attempts,
        claim_token=item.claim_token,
    )


def _heard(
    appended: set[tuple[UUID, str]], held: Mapping[UUID, object]
) -> list[ClaimantControlView]:
    """The appends to items the claimant holds, taken out of `appended`; an
    append to any other item stays there for the next read to settle."""
    found = sorted(entry for entry in appended if entry[0] in held)
    appended.difference_update(found)
    return [
        ClaimantControlView(kind=ClaimantControlKind.APPENDED, item_id=item_id, stream_kind=kind)
        for item_id, kind in found
    ]


class HostsServiceImpl(HostsServiceInterface):
    """A claimant's control stream rides `topics`, and `reader` names the
    claimant kind that reads a stream kind (`KindStreamsInterface.reader`).
    `poll` is how long the stream waits for a wake before it reads the
    claimant's holding again and pings. `spacing` is the least time between
    two of its reads, however many wakes come: a wake is answered at once,
    and the reads the wakes within it ask for are one read."""

    def __init__(
        self,
        hosts: HostsManagerInterface,
        cloud_pool: CloudPoolManagerInterface,
        topics: TopicsInterface,
        reader: Callable[[str], str | None] = lambda kind: None,
        *,
        poll: timedelta = timedelta(seconds=5),
        spacing: timedelta = timedelta(seconds=1),
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._hosts = hosts
        self._cloud_pool = cloud_pool
        self._topics = topics
        self._reader = reader
        self._poll = poll
        self._spacing = spacing
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter

    async def create_pool(
        self, ctx: TenantContext, body: CreatePoolRequest, pool_id: UUID
    ) -> PoolView:
        now = utcnow()
        pool = HostPool(
            id=pool_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            name=body.name,
            region=body.region,
            labels=tuple(body.labels),
        )
        return pool_view(await self._hosts.create_pool(ctx, pool))

    async def get_pools(self, ctx: TenantContext) -> list[PoolView]:
        return [pool_view(pool) for pool in await self._hosts.get_pools(ctx)]

    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> list[HostView]:
        return [status_view(status) for status in await self._hosts.get_hosts(ctx, pool_id)]

    async def get_claimants(self, ctx: TenantContext, pool_id: UUID) -> list[ClaimantView]:
        return [claimant_view(found) for found in await self._hosts.get_claimants(ctx, pool_id)]

    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID, body: IssueEnrollmentTokenRequest | None
    ) -> IssuedEnrollmentTokenView:
        kind = (body or IssueEnrollmentTokenRequest()).kind
        issued = await self._hosts.issue_enrollment_token(ctx, pool_id, kind)
        return IssuedEnrollmentTokenView(
            token=issued.token, enrollment=token_view(issued.enrollment)
        )

    async def revoke_enrollment_token(
        self, ctx: TenantContext, token_id: UUID
    ) -> EnrollmentTokenView:
        return token_view(await self._hosts.revoke_enrollment_token(ctx, token_id))

    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> HostView:
        return host_view(await self._hosts.revoke_host(ctx, host_id), online=False)

    async def revoke_claimant(self, ctx: TenantContext, claimant_id: UUID) -> ClaimantView:
        return claimant_view(await self._hosts.revoke_claimant(ctx, claimant_id))

    async def place_session(
        self, ctx: TenantContext, agent_session_id: UUID, body: PlaceAgentSessionRequest
    ) -> PlacementView:
        await self._hosts.place_session(ctx, agent_session_id, body.pool_id)
        return await self.placement_of(ctx, agent_session_id)

    async def placement_of(self, ctx: TenantContext, agent_session_id: UUID) -> PlacementView:
        state = await self._hosts.placement_of(ctx, agent_session_id)
        return PlacementView(
            agent_session_id=state.agent_session_id,
            pool=None if state.pool is None else pool_view(state.pool),
            hosts_online=state.hosts_online,
            waiting=state.waiting,
            version=state.version,
        )

    async def enroll(
        self, rctx: RequestContext, token: str, body: EnrollRequest
    ) -> IssuedHostCredentialView:
        enrollment = Enrollment(
            name=body.name,
            advertisement=advertisement(body.advertisement),
            exec_version=body.exec_version,
        )
        return credential_view(await self._hosts.enroll(rctx, token, enrollment))

    async def enroll_vm(
        self, rctx: RequestContext, key: str, body: EnrollRequest
    ) -> IssuedHostCredentialView:
        enrollment = Enrollment(
            name=body.name,
            advertisement=advertisement(body.advertisement),
            exec_version=body.exec_version,
        )
        return credential_view(await self._cloud_pool.enroll(rctx, key, enrollment))

    async def rotate(self, rctx: RequestContext, host: HostIdentity) -> IssuedHostCredentialView:
        return credential_view(await self._hosts.rotate(rctx, host))

    async def heartbeat(
        self, rctx: RequestContext, host: HostIdentity, body: HeartbeatRequest
    ) -> HostView:
        report = HostReport(
            advertisement=advertisement(body.advertisement), exec_version=body.exec_version
        )
        seen = await self._hosts.heartbeat(rctx, host, report)
        return host_view(seen, online=at_or_above_floor(WireType.EXEC, seen.exec_version))

    async def claim(
        self, rctx: RequestContext, host: HostIdentity, body: ClaimRequest
    ) -> ClaimView:
        claimed = await self._hosts.claim(rctx, host, body.exec_version)
        if claimed is None:
            return ClaimView(item=None)
        ctx, item = claimed
        return ClaimView(
            item=ClaimedWorkView(
                id=item.id,
                org_id=ctx.org_id,
                kind=item.kind,
                target_id=item.target_id,
                payload=thaw_mapping(item.payload),
                lease_expires_at=item.lease_expires_at,
                attempts=item.attempts,
                wire_version=WIRE_VERSION[WireType.EXEC],
            )
        )

    async def enroll_claimant(
        self, rctx: RequestContext, token: str, body: ClaimantEnrollRequest
    ) -> IssuedClaimantCredentialView:
        enrollment = ClaimantEnrollment(name=body.name)
        issued = await self._hosts.enroll_claimant(rctx, token, enrollment)
        return claimant_credential_view(issued)

    async def rotate_claimant(
        self, rctx: RequestContext, claimant: ClaimantIdentity
    ) -> IssuedClaimantCredentialView:
        return claimant_credential_view(await self._hosts.rotate(rctx, claimant))

    async def claim_as(self, rctx: RequestContext, claimant: ClaimantIdentity) -> ClaimantClaimView:
        claimed = await self._hosts.claim_as(rctx, claimant)
        if claimed is None:
            return ClaimantClaimView(item=None)
        ctx, item = claimed
        return ClaimantClaimView(item=work_view(ctx.org_id, item))

    async def held_as(
        self, rctx: RequestContext, claimant: ClaimantIdentity, item_id: UUID, claim_token: UUID
    ) -> ClaimantWorkView:
        item = await self._hosts.held_as(rctx, claimant, item_id, claim_token)
        return work_view(claimant.org_id, item)

    async def control(
        self, rctx: RequestContext, claimant: ClaimantIdentity, items: Sequence[UUID]
    ) -> AsyncIterator[ClaimantControlView]:
        try:
            holding = await self._hosts.holding_as(rctx, claimant)
        except CredentialExpired:
            return
        claims = {lane: frozenset(kinds) for lane, kinds in holding.claims}
        woken = asyncio.Event()
        work: list[bool] = []
        appended: set[tuple[UUID, str]] = set()

        async def on_work(payload: TopicPayload) -> None:
            if (
                isinstance(payload, WorkAvailablePayload)
                and payload.org_id == claimant.org_id
                and payload.kind in claims.get(payload.lane, frozenset())
            ):
                work.append(True)
                woken.set()

        async def on_append(payload: TopicPayload) -> None:
            if (
                isinstance(payload, StreamAppendedPayload)
                and payload.org_id == claimant.org_id
                and self._reader(payload.kind) == claimant.kind
            ):
                appended.add((payload.group, payload.kind))
                woken.set()

        consumer = f"claimant-control:{claimant.id}"
        unsubscribes = [
            self._topics.subscribe(Topics.WORK_AVAILABLE, consumer, on_work),
            self._topics.subscribe(Topics.STREAM_APPENDED, consumer, on_append),
        ]
        try:
            # A claimant that opens its stream claims at once: a wake it
            # missed while it was away is not lost.
            yield ClaimantControlView(kind=ClaimantControlKind.WAKE)
            # The items it names hold until the first read says otherwise.
            held: dict[UUID, UUID | None] = dict.fromkeys(items)
            opened = read = self._clock()
            span = STREAM_SPAN * (1 - SPAN_JITTER * self._jitter())
            while True:
                if holding.whole:
                    now_held: dict[UUID, UUID | None] = dict(holding.items)
                    for item_id, token in held.items():
                        if item_id not in now_held or token not in (None, now_held[item_id]):
                            yield ClaimantControlView(
                                kind=ClaimantControlKind.REVOKE, item_id=item_id
                            )
                    held = now_held
                else:
                    # Past the most one read returns, an item it does not
                    # list may still be held: none is revoked on its word.
                    held.update(holding.items)
                for view in _heard(appended, held):
                    yield view
                appended.clear()
                if work:
                    work.clear()
                    yield ClaimantControlView(kind=ClaimantControlKind.WAKE)
                now = self._clock()
                if now >= claimant.expires_at or now - opened >= span:
                    # It ends, and the claimant opens the next with the
                    # credential it holds then, as a host does.
                    return
                wait = min(self._poll, opened + span - now)
                try:
                    await asyncio.wait_for(woken.wait(), wait.total_seconds())
                except TimeoutError:
                    yield ClaimantControlView(kind=ClaimantControlKind.PING)
                else:
                    # Work, and an append to an item read as held, need no
                    # read: each is said at once.
                    if work:
                        work.clear()
                        yield ClaimantControlView(kind=ClaimantControlKind.WAKE)
                    for view in _heard(appended, held):
                        yield view
                # A burst of wakes is one read, not a read each.
                rest = read + self._spacing - self._clock()
                if rest > timedelta(0):
                    await self._sleep(rest.total_seconds())
                woken.clear()
                read = self._clock()
                try:
                    holding = await self._hosts.holding_as(rctx, claimant)
                except CredentialExpired:
                    # Revoked while its stream was open: it ends with it.
                    return
        finally:
            for unsubscribe in unsubscribes:
                unsubscribe()

    async def extend_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        body: ExtendLeaseRequest,
    ) -> ClaimantWorkView:
        item = await self._hosts.extend_as(rctx, claimant, item_id, body.claim_token)
        return work_view(claimant.org_id, item)

    async def report_as(
        self,
        rctx: RequestContext,
        claimant: ClaimantIdentity,
        item_id: UUID,
        body: ClaimantReportRequest,
    ) -> ClaimantWorkView:
        item = await self._hosts.report_as(rctx, claimant, body.report(item_id))
        return work_view(claimant.org_id, item)
