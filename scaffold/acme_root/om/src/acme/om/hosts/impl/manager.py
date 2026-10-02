import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.infra.observability import OUTCOMES
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import AppContext, Permission, RequestContext, TenantContext
from acme.om.exceptions import (
    CredentialExpired,
    InvalidCredential,
    NotFound,
    ValidationFailed,
)
from acme.om.hosts.exceptions import VersionBelowFloor
from acme.om.hosts.manager import HostsManagerInterface
from acme.om.hosts.rules import (
    ENROLLMENT_PREFIX,
    HOST_CREDENTIAL_PREFIX,
    WIRE_FLOOR,
    WireType,
    at_or_above_floor,
    online,
    retired_at,
)
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.types.credential import (
    EnrollmentToken,
    HostCredential,
    IssuedEnrollmentToken,
    IssuedHostCredential,
    Rotation,
)
from acme.om.hosts.types.host import Enrollment, Host, HostIdentity, HostReport, HostStatus
from acme.om.hosts.types.placement import PlacementState, SessionPlacement
from acme.om.hosts.types.pool import HostPool
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, outbox_row, versioned_row
from acme.om.placement import PlacementManagerInterface
from acme.om.placement.types.claimant import Claimant, ClaimantKind
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.rules import hash_token
from acme.om.work.types.work_item import WorkItem

log = logging.getLogger(__name__)

POOL_CREATED_KIND = "hosts.pool.created"
TOKEN_ISSUED_KIND = "hosts.enrollment_token.created"
TOKEN_REVOKED_KIND = "hosts.enrollment_token.revoked"
HOST_ENROLLED_KIND = "hosts.host.created"
HOST_REVOKED_KIND = "hosts.host.revoked"
PLACEMENT_KIND = "hosts.session_placement.updated"


class HostsOptions(Platform):
    # An enrollment token lives a day: long enough to install a few hosts,
    # short enough that one left in a script does not let hosts in for long.
    enrollment_ttl: timedelta = timedelta(days=1)
    # A host credential lives an hour, and the host rotates it at half its
    # life. It rotates once, and is refused past its grace once rotated: a
    # copy taken from a disk lasts until the host or the copy presents a
    # credential the other rotated, which ends the host and both.
    credential_ttl: timedelta = timedelta(hours=1)
    # A rotated credential still works this long, so a call in flight with
    # it lands. It never rotates again.
    rotation_grace: timedelta = timedelta(minutes=1)
    # A host that called within this window is online: three of its beats.
    online_window: timedelta = timedelta(seconds=90)
    # How long a host holds what it claimed before the sweep takes it back.
    claim_lease: timedelta = timedelta(seconds=60)
    max_pools: int = 200
    max_hosts: int = 1000  # the most hosts of one pool read at once
    purge_batch: int = 1000


class Provenance(Platform):
    """What a host's write records as its provenance: the person who issued
    the token the host enrolled with, under the host's request. A host is no
    person and acts for nobody, so the person who let it in answers for it."""

    org_id: UUID
    user_id: UUID
    request_id: UUID
    app: AppContext
    traceparent: str | None = None


def provenance(rctx: RequestContext, org_id: UUID, user_id: UUID) -> Provenance:
    return Provenance(
        org_id=org_id,
        user_id=user_id,
        request_id=rctx.request_id,
        app=rctx.app,
        traceparent=rctx.traceparent,
    )


def mint(prefix: str) -> tuple[str, str]:
    """A fresh secret under its kind's prefix, and the digest that is kept."""
    secret = prefix + secrets.token_urlsafe(32)
    return secret, hash_token(secret)


class HostsManagerImpl(HostsManagerInterface):
    def __init__(
        self,
        storage: HostsStorageInterface,
        placement: PlacementManagerInterface,
        sessions: AgentSessionsManagerInterface,
        tenancy: TenancyManagerInterface,
        relay: OutboxRelayInterface,
        options: HostsOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._placement = placement
        self._sessions = sessions
        self._tenancy = tenancy
        self._relay = relay
        self._options = options
        self._clock = clock

    # A tenant's side.

    async def create_pool(self, ctx: TenantContext, pool: HostPool) -> HostPool:
        ctx.require(Permission.MANAGE_MEMBERS)
        now = self._clock()
        created = pool.model_copy(
            update={
                "created_at": now,
                "updated_at": now,
                "created_by": ctx.user_id,
                "updated_by": ctx.user_id,
            }
        )
        rows = (outbox_row(ctx, POOL_CREATED_KIND, created.id, {}),)
        if not await self._storage.create_pool(ctx.org_id, created, rows):
            stored = await self._storage.read_pool(ctx.org_id, created.id)
            if stored is None:
                raise NotFound(f"pool {created.id} not found")
            return stored
        await self._relay.relay_all(ctx.org_id, rows)
        return created

    async def get_pools(self, ctx: TenantContext) -> tuple[HostPool, ...]:
        ctx.require(Permission.READ)
        return tuple(await self._storage.read_pools(ctx.org_id, self._options.max_pools))

    async def get_hosts(self, ctx: TenantContext, pool_id: UUID) -> tuple[HostStatus, ...]:
        ctx.require(Permission.READ)
        await self._pool(ctx, pool_id)
        now = self._clock()
        window = self._options.online_window
        return tuple(
            HostStatus(host=host, online=online(host, now, window))
            for host in await self._storage.read_hosts(ctx.org_id, pool_id, self._options.max_hosts)
        )

    async def issue_enrollment_token(
        self, ctx: TenantContext, pool_id: UUID
    ) -> IssuedEnrollmentToken:
        ctx.require(Permission.MANAGE_MEMBERS)
        await self._pool(ctx, pool_id)
        secret, digest = mint(ENROLLMENT_PREFIX)
        now = self._clock()
        token = EnrollmentToken(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            pool_id=pool_id,
            digest=digest,
            expires_at=now + self._options.enrollment_ttl,
        )
        rows = (outbox_row(ctx, TOKEN_ISSUED_KIND, token.id, {"pool_id": str(pool_id)}),)
        await self._storage.create_enrollment_token(ctx.org_id, token, rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return IssuedEnrollmentToken(token=secret, enrollment=token)

    async def revoke_enrollment_token(self, ctx: TenantContext, token_id: UUID) -> EnrollmentToken:
        ctx.require(Permission.MANAGE_MEMBERS)
        rows = (outbox_row(ctx, TOKEN_REVOKED_KIND, token_id, {}),)
        revoked = await self._storage.revoke_enrollment_token(
            ctx.org_id, token_id, self._clock(), ctx.user_id, rows
        )
        if revoked is None:
            raise NotFound(f"enrollment token {token_id} not found")
        await self._relay.relay_all(ctx.org_id, rows)
        return revoked

    async def revoke_host(self, ctx: TenantContext, host_id: UUID) -> Host:
        ctx.require(Permission.MANAGE_MEMBERS)
        rows = (outbox_row(ctx, HOST_REVOKED_KIND, host_id, {}),)
        revoked = await self._storage.revoke_host(
            ctx.org_id, host_id, self._clock(), ctx.user_id, rows
        )
        if revoked is None:
            raise NotFound(f"host {host_id} not found")
        await self._relay.relay_all(ctx.org_id, rows)
        return revoked

    async def place_session(
        self, ctx: TenantContext, session_id: UUID, pool_id: UUID | None
    ) -> SessionPlacement:
        ctx.require(Permission.WRITE)
        session = await self._sessions.get_session(ctx, session_id)
        if session.root_id != session.id:
            raise ValidationFailed(
                f"session {session_id} is a sub-agent: it runs where its root "
                f"{session.root_id} runs, so place its root"
            )
        if pool_id is not None:
            await self._pool(ctx, pool_id)
        stored = await self._storage.read_placement(ctx.org_id, session_id)
        now = self._clock()
        if stored is None:
            placed = SessionPlacement(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                session_id=session_id,
                pool_id=pool_id,
            )
        else:
            placed = stored.model_copy(
                update={
                    "pool_id": pool_id,
                    "updated_at": now,
                    "updated_by": ctx.user_id,
                    "version": stored.version + 1,
                }
            )
        rows = (versioned_row(ctx, PLACEMENT_KIND, session_id, placed.version),)
        expected = 0 if stored is None else stored.version
        await self._storage.write_placement(ctx.org_id, placed, expected, rows)
        await self._relay.relay_all(ctx.org_id, rows)
        return placed

    async def placement_of(self, ctx: TenantContext, session_id: UUID) -> PlacementState:
        ctx.require(Permission.READ)
        session = await self._sessions.get_session(ctx, session_id)
        # A sub-agent runs where its tree's root runs.
        placed = await self._storage.read_placement(ctx.org_id, session.root_id)
        if placed is None:
            return PlacementState(session_id=session_id)
        if placed.pool_id is None:
            return PlacementState(session_id=session_id, version=placed.version)
        pool = await self._storage.read_pool(ctx.org_id, placed.pool_id)
        if pool is None:
            # A pinned session whose pool is gone stays pinned to it: it waits,
            # and never falls back to the cloud.
            raise NotFound(f"pool {placed.pool_id} of session {session_id} not found")
        now = self._clock()
        window = self._options.online_window
        hosts = await self._storage.read_hosts(ctx.org_id, pool.id, self._options.max_hosts)
        return PlacementState(
            session_id=session_id,
            pool=pool,
            hosts_online=sum(1 for host in hosts if online(host, now, window)),
            version=placed.version,
        )

    async def purge_tenant(self, ctx: TenantContext) -> int:
        ctx.require(Permission.WRITE)
        if not await self._tenancy.tenant_expired(ctx):
            return 0
        return await self._storage.purge_tenant(ctx.org_id, self._options.purge_batch)

    # A host's side.

    async def enroll(
        self, rctx: RequestContext, token: str, enrollment: Enrollment
    ) -> IssuedHostCredential:
        if not token.startswith(ENROLLMENT_PREFIX):
            raise InvalidCredential("a host enrolls with an enrollment token")
        found = await self._storage.read_enrollment_token_by_digest(hash_token(token))
        if found is None:
            raise InvalidCredential("unknown enrollment token")
        org_id, enrollment_token = found
        now = self._clock()
        if enrollment_token.revoked_at is not None or enrollment_token.expires_at <= now:
            raise CredentialExpired("enrollment token expired or revoked")
        self._at_or_above_floor(enrollment.exec_version)
        host = Host(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=enrollment_token.created_by,
            updated_by=enrollment_token.created_by,
            pool_id=enrollment_token.pool_id,
            name=enrollment.name,
            enrolled_with=enrollment_token.id,
            advertisement=enrollment.advertisement,
            exec_version=enrollment.exec_version,
            last_seen_at=now,
        )
        secret, credential = self._credential(host.id, now)
        rows: tuple[OutboxRow, ...] = (
            outbox_row(
                provenance(rctx, org_id, enrollment_token.created_by),
                HOST_ENROLLED_KIND,
                host.id,
                {"pool_id": str(host.pool_id), "enrolled_with": str(enrollment_token.id)},
            ),
        )
        await self._storage.enroll_host(org_id, host, credential, rows)
        await self._relay.relay_all(org_id, rows)
        OUTCOMES.labels(subsystem="hosts", outcome="enrolled").inc()
        return self._issued(secret, credential, host)

    async def authenticate(self, rctx: RequestContext, credential: str) -> HostIdentity:
        if not credential.startswith(HOST_CREDENTIAL_PREFIX):
            raise InvalidCredential("a host calls with its own credential")
        found = await self._storage.read_host_by_credential_digest(hash_token(credential))
        if found is None:
            raise InvalidCredential("unknown host credential")
        org_id, held, host = found
        now = self._clock()
        if host.revoked_at is not None:
            raise CredentialExpired("host revoked")
        if held.expires_at <= now:
            if held.rotated_at is not None:
                # A rotated credential past its grace: the machine that
                # rotated it holds the next one, so whoever presents this
                # one is a second machine, or the first is.
                await self._reused(rctx, org_id, host, now)
                raise CredentialExpired(
                    "host credential rotated already; the host and its credentials are revoked"
                )
            raise CredentialExpired("host credential expired")
        return HostIdentity(
            host_id=host.id,
            org_id=org_id,
            pool_id=host.pool_id,
            credential_id=held.id,
            expires_at=held.expires_at,
        )

    async def rotate(self, rctx: RequestContext, host: HostIdentity) -> IssuedHostCredential:
        stored = await self._live(host)
        now = self._clock()
        secret, minted = self._credential(host.host_id, now)
        retire_at = retired_at(host.expires_at, now, self._options.rotation_grace)
        rotation = await self._storage.rotate_credential(
            host.org_id, host.credential_id, now, retire_at, minted
        )
        if rotation is Rotation.REUSED:
            await self._reused(rctx, host.org_id, stored, now)
            raise CredentialExpired(
                "host credential rotated already; the host and its credentials are revoked"
            )
        if rotation is Rotation.MISSING:
            raise CredentialExpired("host credential expired, rotated, or revoked")
        return IssuedHostCredential(
            credential=secret,
            credential_id=minted.id,
            host_id=host.host_id,
            pool_id=host.pool_id,
            expires_at=minted.expires_at,
        )

    async def heartbeat(self, rctx: RequestContext, host: HostIdentity, report: HostReport) -> Host:
        await self._live(host)
        await self._seen(host, report)
        return await self._live(host)

    async def claim(
        self, rctx: RequestContext, host: HostIdentity, exec_version: int
    ) -> tuple[TenantContext, WorkItem] | None:
        self._at_or_above_floor(exec_version)
        stored = await self._live(host)
        await self._seen(
            host, HostReport(advertisement=stored.advertisement, exec_version=exec_version)
        )
        # The claimant is the identity the credential resolved to: the host,
        # the tenant whose wall it sits in, and the pool its enrollment named.
        claimant = Claimant(
            kind=ClaimantKind.HOST, id=host.host_id, org_id=host.org_id, pool_id=host.pool_id
        )
        return await self._placement.claim_for(rctx, claimant, self._options.claim_lease)

    # Helpers.

    async def _pool(self, ctx: TenantContext, pool_id: UUID) -> HostPool:
        pool = await self._storage.read_pool(ctx.org_id, pool_id)
        if pool is None:
            raise NotFound(f"pool {pool_id} not found")
        return pool

    async def _live(self, host: HostIdentity) -> Host:
        """The host behind an identity, refused once it is revoked: a call
        that resolved its credential a moment before the revoke is handed
        nothing after it."""
        stored = await self._storage.read_host(host.org_id, host.host_id)
        if stored is None or stored.revoked_at is not None:
            raise CredentialExpired("host revoked")
        return stored

    async def _reused(self, rctx: RequestContext, org_id: UUID, host: Host, at: datetime) -> None:
        """A credential that rotated already, presented to rotate again or
        after its grace: two machines hold the host's identity, the host and
        a copy. Neither can be told from the other, so the host and every
        credential it holds end, and its owner reads it revoked and enrolls
        it again. The person who let it in answers for the revocation, as
        for every write of the host's."""
        rows = (
            outbox_row(
                provenance(rctx, org_id, host.created_by),
                HOST_REVOKED_KIND,
                host.id,
                {"reason": "credential_reused"},
            ),
        )
        await self._storage.revoke_host(org_id, host.id, at, host.created_by, rows)
        await self._relay.relay_all(org_id, rows)
        OUTCOMES.labels(subsystem="hosts", outcome="credential_reused").inc()
        log.warning("host %s: a rotated credential was presented again; revoked", host.id)

    async def _seen(self, host: HostIdentity, report: HostReport) -> None:
        if not await self._storage.mark_seen(host.org_id, host.host_id, self._clock(), report):
            raise CredentialExpired("host revoked")

    def _credential(self, host_id: UUID, now: datetime) -> tuple[str, HostCredential]:
        secret, digest = mint(HOST_CREDENTIAL_PREFIX)
        credential = HostCredential(
            id=new_id(),
            created_at=now,
            host_id=host_id,
            digest=digest,
            expires_at=now + self._options.credential_ttl,
        )
        return secret, credential

    @staticmethod
    def _issued(secret: str, credential: HostCredential, host: Host) -> IssuedHostCredential:
        return IssuedHostCredential(
            credential=secret,
            credential_id=credential.id,
            host_id=host.id,
            pool_id=host.pool_id,
            expires_at=credential.expires_at,
        )

    @staticmethod
    def _at_or_above_floor(exec_version: int) -> None:
        if not at_or_above_floor(WireType.EXEC, exec_version):
            OUTCOMES.labels(subsystem="hosts", outcome="below_floor").inc()
            raise VersionBelowFloor(
                f"this host reads exec work at version {exec_version}; "
                f"the platform hands work to version {WIRE_FLOOR[WireType.EXEC]} and later"
            )
