"""Hosts over memory: a host enrolls once with its tenant's token and gets a
credential of its own kind, short-lived and rotating; it is handed only
the work pinned to its pool, by its identity, and none while it reads a
version below the floor; and a session pinned to a pool with no host online
waits, says so, and never moves to the cloud."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from unit.test_placement import exec_on

from acme.infra.impl.local import InfraLocalImpl
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import (
    CredentialExpired,
    InvalidCredential,
    NotAuthorized,
    NotFound,
    ValidationFailed,
)
from acme.om.hosts import rules
from acme.om.hosts.exceptions import PinnedToHosts, VersionBelowFloor
from acme.om.hosts.impl.manager import HostsManagerImpl, HostsOptions
from acme.om.hosts.impl.placement import PlacementHostsImpl
from acme.om.hosts.rules import ENROLLMENT_PREFIX, WireType
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import Advertisement, Enrollment, HostReport, IsolationMode
from acme.om.hosts.types.pool import HostPool
from acme.om.placement.kinds import HOST, HOST_PREFIX, platform_claimant_kinds
from acme.om.placement.rules import host_lane, pool_lane
from acme.om.placement.types.claimant import Claimant
from acme.om.placement.types.work import WorkspaceOperation
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import CREDENTIAL_PREFIXES, credential_kind_of
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.types.work_item import WorkItem, WorkKind

APP = AppContext(type=AppType.PORTAL, version="portal@test")
HOST_APP = AppContext(type=AppType.API, version="host@test")
PROBED = Advertisement(
    os="Linux 6.8",
    shell="/bin/bash",
    capabilities=("git",),
    isolation_modes=(IsolationMode.CONTAINER,),
)
CLOUD_POOL = new_id()
"""The pool of the platform's own hosts, in its cloud."""


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


def request(app: AppContext = HOST_APP) -> RequestContext:
    return RequestContext(request_id=new_id(), app=app)


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(tmp_path: Path, storage: StorageMemoryImpl) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hosts(managers: Managers, storage: StorageMemoryImpl, clock: Clock) -> HostsManagerImpl:
    """The hosts manager the root builds, on a clock the case moves."""
    return HostsManagerImpl(
        storage.get_hosts_storage(),
        managers.placement,
        managers.agent_sessions,
        managers.tenancy,
        managers.outbox,
        HostsOptions(),
        platform_claimant_kinds(),
        clock=clock,
    )


async def an_owner(managers: Managers, slug: str = "ajax") -> TenantContext:
    owner, _ = await managers.tenancy.bootstrap(
        request(APP), slug.title(), slug, f"ann@{slug}.test", "Ann"
    )
    return owner


async def a_member(managers: Managers, slug: str, role: Role) -> TenantContext:
    owner, user, _ = await managers.tenancy.add_member(
        request(APP), slug, f"{role.value}@{slug}.test", role.value.title(), role
    )
    return await managers.tenancy.member_context(request(APP), owner.org_id, user.id)


def a_pool(name: str = "build") -> HostPool:
    now = utcnow()
    return HostPool(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        name=name,
        region="eu-west",
    )


def an_item(ctx: TenantContext, kind: WorkKind, payload: Mapping[str, object]) -> WorkItem:
    now = utcnow()
    return WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=kind,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload=payload,
        available_at=now,
    )


def prepare_in(pool: UUID) -> dict[str, object]:
    return {"operation": WorkspaceOperation.PREPARE.value, "pool_id": str(pool)}


async def enrolled(
    hosts: HostsManagerImpl, owner: TenantContext, pool: HostPool, name: str = "host-1"
) -> IssuedCredential:
    issued = await hosts.issue_enrollment_token(owner, pool.id)
    return await hosts.enroll(
        request(), issued.token, Enrollment(name=name, advertisement=PROBED, exec_version=1)
    )


# A host's credential is its own: minted only from an enrollment token, of a
# kind and prefix of its own, short-lived, and rotated.


async def test_a_host_enrolls_into_its_tokens_pool_with_a_credential_of_its_own(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    issued = await hosts.issue_enrollment_token(owner, pool.id)
    assert issued.token.startswith(ENROLLMENT_PREFIX)
    assert issued.token not in issued.enrollment.digest
    credential = await hosts.enroll(
        request(), issued.token, Enrollment(name="host-1", advertisement=PROBED, exec_version=1)
    )
    assert credential.credential.startswith(HOST_PREFIX)
    assert credential.pool_id == pool.id
    assert credential.expires_at == clock.now + HostsOptions().credential_ttl
    # A kind of its own: no prefix a person's or an agent's credential takes.
    assert not any(credential.credential.startswith(prefix) for prefix in CREDENTIAL_PREFIXES)
    assert credential_kind_of(credential.credential) is None
    host = await hosts.authenticate(request(), credential.credential)
    assert (host.host_id, host.org_id, host.pool_id) == (
        credential.claimant_id,
        owner.org_id,
        pool.id,
    )
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.online and status.host.created_by == owner.user_id
    assert status.host.advertisement == PROBED


async def test_only_a_live_enrollment_token_enrolls_a_host(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    host = await enrolled(hosts, owner, pool)
    key = await managers.tenancy.credentials.create_api_key(owner, "ci", Role.MEMBER)
    enrollment = Enrollment(name="host-2", advertisement=PROBED, exec_version=1)
    # A platform credential, the host's own, and a forged token are refused.
    for credential in (key.key, host.credential, ENROLLMENT_PREFIX + "forged"):
        with pytest.raises(InvalidCredential):
            await hosts.enroll(request(), credential, enrollment)
    expiring = await hosts.issue_enrollment_token(owner, pool.id)
    revoked = await hosts.issue_enrollment_token(owner, pool.id)
    await hosts.revoke_enrollment_token(owner, revoked.enrollment.id)
    with pytest.raises(CredentialExpired):
        await hosts.enroll(request(), revoked.token, enrollment)
    clock.advance(HostsOptions().enrollment_ttl)
    with pytest.raises(CredentialExpired):
        await hosts.enroll(request(), expiring.token, enrollment)
    assert len(await hosts.get_hosts(owner, pool.id)) == 1


async def test_a_token_whose_issuer_left_or_was_lowered_enrolls_nothing(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    leaving = await a_member(managers, "ajax", Role.ADMIN)
    _, user, _ = await managers.tenancy.add_member(
        request(APP), "ajax", "bea@ajax.test", "Bea", Role.ADMIN
    )
    lowered = await managers.tenancy.member_context(request(APP), owner.org_id, user.id)
    left_token = await hosts.issue_enrollment_token(leaving, pool.id)
    lowered_token = await hosts.issue_enrollment_token(lowered, pool.id)
    kept = await hosts.issue_enrollment_token(owner, pool.id)
    await managers.tenancy.members.remove_member(owner, leaving.user_id)
    await managers.tenancy.members.update_membership_role(owner, lowered.user_id, Role.MEMBER)
    enrollment = Enrollment(name="host-1", advertisement=PROBED, exec_version=1)
    for token in (left_token, lowered_token):
        with pytest.raises(CredentialExpired):
            await hosts.enroll(request(), token.token, enrollment)
    assert await hosts.get_hosts(owner, pool.id) == ()
    # A token of an issuer who still manages the members enrolls.
    await hosts.enroll(request(), kept.token, enrollment)
    assert len(await hosts.get_hosts(owner, pool.id)) == 1


async def test_a_host_credential_is_no_platform_credential_and_no_other_is_a_hosts(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    token = await hosts.issue_enrollment_token(owner, pool.id)
    host = await hosts.enroll(
        request(), token.token, Enrollment(name="host-1", advertisement=PROBED, exec_version=1)
    )
    # The tenant's transitions refuse it: a host acts for no person.
    with pytest.raises(InvalidCredential):
        await managers.tenancy.authenticate(request(APP), host.credential)
    # And the host's refuses every credential but its own kind.
    key = await managers.tenancy.credentials.create_api_key(owner, "ci", Role.MEMBER)
    for credential in (key.key, token.token, HOST_PREFIX + "forged"):
        with pytest.raises(InvalidCredential):
            await hosts.authenticate(request(), credential)


async def test_a_credential_lives_an_hour_and_the_host_rotates_it(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    first = await enrolled(hosts, owner, pool)
    clock.advance(timedelta(minutes=30))
    identity = await hosts.authenticate(request(), first.credential)
    second = await hosts.rotate(request(), identity)
    assert second.credential != first.credential and second.claimant_id == first.claimant_id
    assert second.expires_at == clock.now + HostsOptions().credential_ttl
    # The one it replaced works for the grace, so a call in flight with it
    # lands; past it, the host calls with the next one.
    await hosts.authenticate(request(), first.credential)
    clock.advance(HostsOptions().rotation_grace)
    await hosts.authenticate(request(), second.credential)
    # Unrotated, a credential ends with its life, and only it ends.
    clock.advance(HostsOptions().credential_ttl)
    with pytest.raises(CredentialExpired):
        await hosts.authenticate(request(), second.credential)
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.host.revoked_at is None


async def test_a_copy_rotated_after_the_hosts_own_rotation_ends_the_host(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    issued = await enrolled(hosts, owner, pool)
    copy = issued.credential  # taken from the host's disk
    clock.advance(timedelta(minutes=30))
    rotated = await hosts.rotate(request(), await hosts.authenticate(request(), issued.credential))
    # The copy still authenticates in the grace, and rotates: refused, since
    # a credential rotates once, and the host and its credentials end.
    copied = await hosts.authenticate(request(), copy)
    with pytest.raises(CredentialExpired):
        await hosts.rotate(request(), copied)
    for credential in (copy, rotated.credential):
        with pytest.raises(CredentialExpired):
            await hosts.authenticate(request(), credential)
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.host.revoked_at == clock.now and not status.online


async def test_a_copy_rotating_every_half_hour_does_not_outlive_its_hour(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    issued = await enrolled(hosts, owner, pool)
    copy = issued.credential
    # The copy rotates first, at half the credential's life, for a fresh hour.
    clock.advance(timedelta(minutes=30))
    forked = await hosts.rotate(request(), await hosts.authenticate(request(), copy))
    # The host rotates the same credential: two machines hold it, and both end.
    with pytest.raises(CredentialExpired):
        await hosts.rotate(request(), await hosts.authenticate(request(), issued.credential))
    with pytest.raises(CredentialExpired):
        await hosts.authenticate(request(), forked.credential)
    # Every half hour after, the copy is refused, and past the hour nothing
    # it ever held authenticates.
    for _ in range(2):
        clock.advance(timedelta(minutes=30))
        for credential in (copy, forked.credential):
            with pytest.raises(CredentialExpired):
                await hosts.authenticate(request(), credential)


async def test_a_copy_that_rotates_first_ends_at_the_hosts_next_beat(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    issued = await enrolled(hosts, owner, pool)
    # The copy rotates 10 minutes in and every 30 minutes after, while the
    # host is silent, past the grace of the credential it holds.
    clock.advance(timedelta(minutes=10))
    held = await hosts.rotate(request(), await hosts.authenticate(request(), issued.credential))
    for _ in range(2):
        clock.advance(timedelta(minutes=30))
        held = await hosts.rotate(request(), await hosts.authenticate(request(), held.credential))
    # The host's next beat, with the credential the copy rotated away from:
    # refused, and the host and every credential it holds are revoked.
    with pytest.raises(CredentialExpired):
        await hosts.authenticate(request(), issued.credential)
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.host.revoked_at == clock.now and not status.online
    with pytest.raises(CredentialExpired):
        await hosts.authenticate(request(), held.credential)


async def test_a_revoked_host_is_refused_and_handed_nothing(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    host = await enrolled(hosts, owner, pool)
    identity = await hosts.authenticate(request(), host.credential)
    await managers.work.enqueue(owner, an_item(owner, WorkKind.WORKSPACE, prepare_in(pool.id)))
    await hosts.revoke_host(owner, host.claimant_id)
    with pytest.raises(CredentialExpired):
        await hosts.authenticate(request(), host.credential)
    # A call that resolved its credential before the revoke is handed nothing.
    with pytest.raises(CredentialExpired):
        await hosts.claim(request(), identity, 1)
    with pytest.raises(CredentialExpired):
        await hosts.rotate(request(), identity)
    with pytest.raises(CredentialExpired):
        await hosts.heartbeat(request(), identity, HostReport(advertisement=PROBED, exec_version=1))
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert not status.online


async def test_only_an_owner_or_an_admin_lets_hosts_in(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    member = await a_member(managers, "ajax", Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await hosts.create_pool(member, a_pool())
    with pytest.raises(NotAuthorized):
        await hosts.issue_enrollment_token(member, pool.id)
    host = await enrolled(hosts, owner, pool)
    with pytest.raises(NotAuthorized):
        await hosts.revoke_host(member, host.claimant_id)
    other = await an_owner(managers, "fabrikam")
    with pytest.raises(NotFound):
        await hosts.issue_enrollment_token(other, pool.id)
    with pytest.raises(NotFound):
        await hosts.revoke_host(other, host.claimant_id)


# A host is handed only the work pinned to its pool, by its identity, and
# none while it reads a version below the floor.


async def test_a_host_is_handed_only_the_work_pinned_to_its_pool(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    ours, theirs = (
        await hosts.create_pool(owner, a_pool("a")),
        await hosts.create_pool(owner, a_pool("b")),
    )
    other = await an_owner(managers, "fabrikam")
    foreign = await hosts.create_pool(other, a_pool("c"))
    ours_host = await enrolled(hosts, owner, ours, "host-a")
    theirs_host = await enrolled(hosts, owner, theirs, "host-b")
    mine = await managers.work.enqueue(
        owner, an_item(owner, WorkKind.WORKSPACE, prepare_in(ours.id))
    )
    pinned_elsewhere = await managers.work.enqueue(
        owner, an_item(owner, WorkKind.WORKSPACE, prepare_in(theirs.id))
    )
    on_their_host = await managers.work.enqueue(
        owner, an_item(owner, WorkKind.EXEC, exec_on(theirs_host.claimant_id))
    )
    from_another_tenant = await managers.work.enqueue(
        other, an_item(other, WorkKind.WORKSPACE, prepare_in(foreign.id))
    )
    assert (mine.lane, pinned_elsewhere.lane) == (pool_lane(ours.id), pool_lane(theirs.id))
    assert on_their_host.lane == host_lane(theirs_host.claimant_id)
    identity = await hosts.authenticate(request(), ours_host.credential)
    claimed = await hosts.claim(request(), identity, 1)
    assert claimed is not None and claimed[1].id == mine.id
    assert claimed[1].claimed_by == f"host:{ours_host.claimant_id}"
    assert await hosts.claim(request(), identity, 1) is None
    # What was pinned elsewhere waits there, unclaimed, for its own hosts.
    theirs_identity = await hosts.authenticate(request(), theirs_host.credential)
    handed = set()
    while (next_one := await hosts.claim(request(), theirs_identity, 1)) is not None:
        handed.add(next_one[1].id)
    assert handed == {pinned_elsewhere.id, on_their_host.id}
    assert from_another_tenant.id not in handed


async def test_a_claim_below_the_floor_is_refused_before_anything_is_claimed(
    managers: Managers, hosts: HostsManagerImpl, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    host = await enrolled(hosts, owner, pool)
    item = await managers.work.enqueue(
        owner, an_item(owner, WorkKind.WORKSPACE, prepare_in(pool.id))
    )
    identity = await hosts.authenticate(request(), host.credential)
    with pytest.raises(VersionBelowFloor):
        await hosts.claim(request(), identity, 0)
    # A breaking change raised the floor: the host that still reads version 1
    # is handed nothing, enrolls nothing, and serves its pool no more.
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.EXEC, 2)
    with pytest.raises(VersionBelowFloor):
        await hosts.claim(request(), identity, 1)
    token = await hosts.issue_enrollment_token(owner, pool.id)
    with pytest.raises(VersionBelowFloor):
        await hosts.enroll(
            request(), token.token, Enrollment(name="old", advertisement=PROBED, exec_version=1)
        )
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert not status.online
    # Upgraded, it claims what waited for it.
    claimed = await hosts.claim(request(), identity, 2)
    assert claimed is not None and claimed[1].id == item.id
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.online and status.host.exec_version == 2


async def test_the_platform_keeps_what_a_host_advertised_and_adds_nothing(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    host = await enrolled(hosts, owner, pool)
    identity = await hosts.authenticate(request(), host.credential)
    fewer = PROBED.model_copy(update={"isolation_modes": (), "capabilities": ()})
    seen = await hosts.heartbeat(
        request(), identity, HostReport(advertisement=fewer, exec_version=1)
    )
    assert seen.advertisement == fewer
    # A claim renews the host and keeps what it last advertised.
    await hosts.claim(request(), identity, 1)
    (status,) = await hosts.get_hosts(owner, pool.id)
    assert status.host.advertisement == fewer


# A pinned session waits, visibly, and never moves to the cloud.


async def test_a_pinned_session_with_no_host_online_waits_and_never_moves_to_the_cloud(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    session = await managers.agent_sessions.create_session(owner, make_session())
    assert not (await hosts.placement_of(owner, session.id)).waiting  # the cloud, unplaced
    await hosts.place_session(owner, session.id, pool.id)
    state = await hosts.placement_of(owner, session.id)
    assert state.pool == pool and state.hosts_online == 0 and state.waiting
    # Its workspace is asked of its pool, and no cloud host is handed it,
    # however long it waits.
    prepare = await managers.work.enqueue(
        owner, an_item(owner, WorkKind.WORKSPACE, prepare_in(pool.id))
    )
    assert prepare.lane == pool_lane(pool.id)
    cloud = Claimant(kind=HOST, id=new_id(), pool_id=CLOUD_POOL)
    for _ in range(3):
        assert await managers.placement.claim_for(request(), cloud, timedelta(seconds=30)) is None
        clock.advance(timedelta(days=1))
        state = await hosts.placement_of(owner, session.id)
        assert state.pool == pool and state.waiting
    # A host of its pool comes online: the session stops waiting, and the
    # host is handed the work.
    host = await enrolled(hosts, owner, pool)
    assert not (await hosts.placement_of(owner, session.id)).waiting
    identity = await hosts.authenticate(request(), host.credential)
    claimed = await hosts.claim(request(), identity, 1)
    assert claimed is not None and claimed[1].id == prepare.id
    # The host goes silent: the session waits again, still pinned.
    clock.advance(HostsOptions().online_window)
    state = await hosts.placement_of(owner, session.id)
    assert state.pool == pool and state.waiting


async def test_only_a_principal_with_write_moves_a_session(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    session = await managers.agent_sessions.create_session(owner, make_session())
    placed = await hosts.place_session(owner, session.id, pool.id)
    viewer = await a_member(managers, "ajax", Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await hosts.place_session(viewer, session.id, None)
    assert (await hosts.placement_of(viewer, session.id)).pool == pool
    moved = await hosts.place_session(owner, session.id, None)
    assert (moved.id, moved.version, moved.pool_id) == (placed.id, 2, None)
    state = await hosts.placement_of(owner, session.id)
    assert state.pool is None and not state.waiting and state.version == 2
    other = await an_owner(managers, "fabrikam")
    with pytest.raises(NotFound):
        await hosts.place_session(other, session.id, None)
    other_session = await managers.agent_sessions.create_session(other, make_session())
    with pytest.raises(NotFound):
        await hosts.place_session(other, other_session.id, pool.id)


async def test_purge_tenant_waits_for_the_retention(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers)
    await hosts.create_pool(owner, a_pool())
    assert await hosts.purge_tenant(owner) == 0
    assert len(await hosts.get_pools(owner)) == 1


async def test_trust_reads_a_pinned_session_inside_the_wall_and_runs_none_of_its_calls_in_the_cloud(
    managers: Managers, hosts: HostsManagerImpl, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    session = await managers.agent_sessions.create_session(owner, make_session())
    runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label="runner-1")
    placement = PlacementHostsImpl(
        storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
    )
    assert not await placement.inside_wall(owner.org_id, session.id)
    assert await placement.executor_of(owner.org_id, session.id) == runner
    await hosts.place_session(owner, session.id, pool.id)
    assert await placement.inside_wall(owner.org_id, session.id)
    # Refused as the loop answers a call it may not make, never run on the
    # runner instead.
    with pytest.raises(PinnedToHosts) as refused:
        await placement.executor_of(owner.org_id, session.id)
    assert isinstance(refused.value, NotAuthorized)
    await hosts.place_session(owner, session.id, None)
    assert await placement.executor_of(owner.org_id, session.id) == runner


async def test_a_sub_agent_runs_where_its_root_runs(
    managers: Managers, hosts: HostsManagerImpl, storage: StorageMemoryImpl
) -> None:
    owner = await an_owner(managers)
    pool = await hosts.create_pool(owner, a_pool())
    root = await managers.agent_sessions.create_session(owner, make_session())
    child = await managers.agent_sessions.create_session(owner, make_session(parent=root))
    grandchild = await managers.agent_sessions.create_session(owner, make_session(parent=child))
    runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label="runner-1")
    placement = PlacementHostsImpl(
        storage.get_hosts_storage(), storage.get_agent_session_storage(), runner
    )
    await hosts.place_session(owner, root.id, pool.id)
    for sub in (child, grandchild):
        assert await placement.inside_wall(owner.org_id, sub.id)
        with pytest.raises(PinnedToHosts):
            await placement.executor_of(owner.org_id, sub.id)
        state = await hosts.placement_of(owner, sub.id)
        assert state.session_id == sub.id and state.pool == pool and state.waiting
    # A sub-agent is never placed apart from its root.
    with pytest.raises(ValidationFailed):
        await hosts.place_session(owner, child.id, None)
    assert await placement.inside_wall(owner.org_id, child.id)
    await hosts.place_session(owner, root.id, None)
    assert await placement.executor_of(owner.org_id, grandchild.id) == runner
