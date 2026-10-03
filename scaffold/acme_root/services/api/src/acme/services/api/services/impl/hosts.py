from uuid import UUID

from acme.om.base import thaw_mapping, utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.rules import WIRE_VERSION, WireType, at_or_above_floor
from acme.om.hosts.types.credential import EnrollmentToken, IssuedHostCredential
from acme.om.hosts.types.host import (
    Advertisement,
    Enrollment,
    Host,
    HostIdentity,
    HostReport,
    HostStatus,
)
from acme.om.hosts.types.pool import HostPool
from acme.services.api.services.hosts import HostsServiceInterface
from acme.services.api.types.hosts import (
    AdvertisementBody,
    AdvertisementView,
    ClaimedWorkView,
    ClaimRequest,
    ClaimView,
    CreatePoolRequest,
    EnrollmentTokenView,
    EnrollRequest,
    HeartbeatRequest,
    HostView,
    IssuedEnrollmentTokenView,
    IssuedHostCredentialView,
    PlacementView,
    PlaceSessionRequest,
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


def credential_view(issued: IssuedHostCredential) -> IssuedHostCredentialView:
    return IssuedHostCredentialView(
        token=issued.credential,
        credential_id=issued.credential_id,
        host_id=issued.host_id,
        pool_id=issued.pool_id,
        expires_at=issued.expires_at,
    )


class HostsServiceImpl(HostsServiceInterface):
    def __init__(self, hosts: HostsManagerInterface) -> None:
        self._hosts = hosts

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

    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID
    ) -> IssuedEnrollmentTokenView:
        issued = await self._hosts.issue_enrollment_token(ctx, pool_id)
        return IssuedEnrollmentTokenView(
            token=issued.token, enrollment=token_view(issued.enrollment)
        )

    async def revoke_enrollment_token(
        self, ctx: TenantContext, token_id: UUID
    ) -> EnrollmentTokenView:
        return token_view(await self._hosts.revoke_enrollment_token(ctx, token_id))

    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> HostView:
        return host_view(await self._hosts.revoke_host(ctx, host_id), online=False)

    async def place_session(
        self, ctx: TenantContext, session_id: UUID, body: PlaceSessionRequest
    ) -> PlacementView:
        await self._hosts.place_session(ctx, session_id, body.pool_id)
        return await self.placement_of(ctx, session_id)

    async def placement_of(self, ctx: TenantContext, session_id: UUID) -> PlacementView:
        state = await self._hosts.placement_of(ctx, session_id)
        return PlacementView(
            session_id=state.session_id,
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
