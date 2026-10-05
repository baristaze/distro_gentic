"""A product's claimant over memory, through the path a host takes: it
enrolls once with a token its tenant issued for its kind and a pool, gets
a short-lived, rotating credential under its kind's prefix, and claims,
reads, renews, and reports only its kind's items in its own tenant's pool,
by its identity alone. A revoked or expired credential is refused. The
example is the `batch` claimant of `test_product_kinds`."""

from pathlib import Path

import pytest
from unit.test_hosts import Clock, a_member, a_pool
from unit.test_product_kinds import (
    BATCH,
    GREEDY,
    PRODUCT,
    RENDER,
    a_render,
    an_owner,
    request,
)

from acme.infra.impl.local import InfraLocalImpl
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.exceptions import (
    CredentialExpired,
    InvalidCredential,
    LeaseLost,
    NotAuthorized,
    NotFound,
    ValidationFailed,
)
from acme.om.hosts.impl.manager import HostsManagerImpl, HostsOptions
from acme.om.hosts.types.credential import IssuedCredential
from acme.om.hosts.types.host import (
    Advertisement,
    ClaimantEnrollment,
    ClaimantIdentity,
    Enrollment,
)
from acme.om.hosts.types.pool import HostPool
from acme.om.placement.kinds import HOST_PREFIX, ClaimantKinds, platform_claimant_kinds
from acme.om.placement.types.claimant import ClaimantReport, ReportOutcome
from acme.om.root import PLATFORM_PREFIXES, Managers, build_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import credential_kind_of
from acme.om.work.types.work_item import WorkStatus

OPTIONS = HostsOptions()


@pytest.fixture
def storage() -> StorageMemoryImpl:
    return StorageMemoryImpl()


@pytest.fixture
def managers(tmp_path: Path, storage: StorageMemoryImpl) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path), product_kinds=PRODUCT)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def hosts(managers: Managers, storage: StorageMemoryImpl, clock: Clock) -> HostsManagerImpl:
    """The hosts manager the root builds, with the product's claimant kinds
    beside the platform's, on a clock the case moves."""
    return HostsManagerImpl(
        storage.get_hosts_storage(),
        managers.placement,
        managers.agent_sessions,
        managers.tenancy,
        managers.outbox,
        OPTIONS,
        ClaimantKinds((*platform_claimant_kinds(), *PRODUCT.claimants), PLATFORM_PREFIXES),
        clock=clock,
        revoked=managers.relay.end_host,
    )


async def a_batch_pool(hosts: HostsManagerImpl, owner: TenantContext) -> HostPool:
    return await hosts.create_pool(owner, a_pool("batch"))


async def a_node(
    hosts: HostsManagerImpl, owner: TenantContext, pool: HostPool, name: str = "node-1"
) -> IssuedCredential:
    issued = await hosts.issue_enrollment_token(owner, pool.id, BATCH)
    return await hosts.enroll_claimant(request(), issued.token, ClaimantEnrollment(name=name))


async def identity_of(hosts: HostsManagerImpl, issued: IssuedCredential) -> ClaimantIdentity:
    return await hosts.authenticate_claimant(request(), issued.credential)


# A product's claimant enrolls as a host does, with a credential of its kind.


async def test_a_products_claimant_enrolls_with_a_credential_of_its_own_kind(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers, "ajax")
    pool = await a_batch_pool(hosts, owner)
    issued = await hosts.issue_enrollment_token(owner, pool.id, BATCH)
    assert issued.enrollment.kind == BATCH
    enrolled = await hosts.enroll_claimant(
        request(), issued.token, ClaimantEnrollment(name="node-1")
    )
    assert enrolled.credential.startswith("bat_") and enrolled.kind == BATCH
    assert credential_kind_of(enrolled.credential) is None, "no tenant route takes it"
    assert enrolled.expires_at == clock.now + OPTIONS.credential_ttl
    identity = await identity_of(hosts, enrolled)
    # The kind, the tenant, and the pool are the credential's, never the call's.
    assert (identity.kind, identity.id, identity.org_id, identity.pool_id) == (
        BATCH,
        enrolled.claimant_id,
        owner.org_id,
        pool.id,
    )
    assert await hosts.get_hosts(owner, pool.id) == (), "a product's claimant is no host"

    # It rotates as a host does: the one it replaced lands for the grace.
    clock.advance(OPTIONS.credential_ttl / 2)
    rotated = await hosts.rotate(request(), identity)
    assert rotated.credential.startswith("bat_") and rotated.claimant_id == enrolled.claimant_id
    assert (await identity_of(hosts, enrolled)).id == enrolled.claimant_id
    clock.advance(OPTIONS.rotation_grace)
    with pytest.raises(CredentialExpired):
        await identity_of(hosts, enrolled)


async def test_each_credential_opens_its_own_kinds_path_alone(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers, "ajax")
    pool = await a_batch_pool(hosts, owner)
    node = await a_node(hosts, owner, pool)
    host_token = await hosts.issue_enrollment_token(owner, pool.id)
    node_token = await hosts.issue_enrollment_token(owner, pool.id, BATCH)
    probed = Enrollment(name="host-1", advertisement=Advertisement(os="Linux"), exec_version=1)
    host = await hosts.enroll(request(), host_token.token, probed)

    # A token enrolls the kind it names, and nothing else.
    with pytest.raises(InvalidCredential, match="enrolls a batch"):
        await hosts.enroll(request(), node_token.token, probed)
    with pytest.raises(InvalidCredential, match="host enrolls with what it probed"):
        await hosts.enroll_claimant(request(), host_token.token, ClaimantEnrollment(name="x"))
    # A credential opens its own kind's calls: a host's are a host's, and a
    # product's claimant never reaches them, nor a host the product's.
    with pytest.raises(InvalidCredential):
        await hosts.authenticate(request(), node.credential)
    with pytest.raises(InvalidCredential):
        await hosts.authenticate_claimant(request(), host.credential)
    host_identity = await hosts.authenticate(request(), host.credential)
    with pytest.raises(InvalidCredential):
        await hosts.claim_as(request(), host_identity)
    for forged in ("bat_forged", "grd_" + node.credential[4:], HOST_PREFIX + "forged", "zzz_x"):
        with pytest.raises(InvalidCredential):
            await hosts.authenticate_claimant(request(), forged)

    # Only an owner or an admin issues a token, and only for a kind the
    # process knows.
    with pytest.raises(ValidationFailed, match="not registered"):
        await hosts.issue_enrollment_token(owner, pool.id, "unknown")
    member = await a_member(managers, "ajax", Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await hosts.issue_enrollment_token(member, pool.id, BATCH)


# Its credential claims only its kind's items in its own tenant's pool.


async def test_a_claimants_credential_claims_only_its_kinds_work_in_its_tenants_pool(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    ajax, beta = await an_owner(managers, "ajax"), await an_owner(managers, "beta")
    ours, elsewhere = await a_batch_pool(hosts, ajax), await a_batch_pool(hosts, ajax)
    node = await identity_of(hosts, await a_node(hosts, ajax, ours))

    # Another pool's render, and another tenant's render routed into this
    # pool, are none of its own.
    other_pool = await managers.work.enqueue(ajax, a_render(ajax, elsewhere.id))
    stray = await managers.work.enqueue(beta, a_render(beta, ours.id))
    mine = await managers.work.enqueue(ajax, a_render(ajax, ours.id))
    # A claimant of another kind, on the same pool, takes none of the render:
    # the render names the batch kind alone.
    greedy_token = await hosts.issue_enrollment_token(ajax, ours.id, GREEDY.name)
    greedy = await hosts.enroll_claimant(
        request(), greedy_token.token, ClaimantEnrollment(name="greedy-1")
    )
    assert greedy.credential.startswith(GREEDY.prefix)
    assert await hosts.claim_as(request(), await identity_of(hosts, greedy)) is None
    claimed = await hosts.claim_as(request(), node)
    assert claimed is not None
    ctx, item = claimed
    assert (ctx.org_id, item.id, item.kind) == (ajax.org_id, mine.id, RENDER)
    assert item.claimed_by == f"{BATCH}:{node.id}" and item.claim_token is not None
    assert await hosts.claim_as(request(), node) is None
    failed = await managers.work.get_item(beta, stray.id)
    assert failed.status is WorkStatus.FAILED, "another tenant's item is never handed over"
    assert (await managers.work.get_item(ajax, other_pool.id)).status is WorkStatus.QUEUED

    # It reads, renews, and reports only what it holds, in its own tenant.
    token = item.claim_token
    assert (await hosts.held_as(request(), node, item.id, token)).id == item.id
    renewed = await hosts.extend_as(request(), node, item.id, token)
    assert renewed.lease_expires_at is not None
    sibling = await identity_of(hosts, await a_node(hosts, ajax, ours, "node-2"))
    for who, item_id in ((sibling, item.id), (node, other_pool.id), (node, stray.id)):
        with pytest.raises(NotFound):
            await hosts.held_as(request(), who, item_id, token)
    with pytest.raises(LeaseLost):
        await hosts.extend_as(request(), node, item.id, new_id())
    done = ClaimantReport(item_id=item.id, claim_token=token, outcome=ReportOutcome.DONE)
    finished = await hosts.report_as(request(), node, done)
    assert finished.status is WorkStatus.DONE


# A revoked or expired credential is refused.


async def test_a_claimant_token_whose_issuer_left_enrolls_nothing(
    managers: Managers, hosts: HostsManagerImpl
) -> None:
    owner = await an_owner(managers, "ajax")
    pool = await a_batch_pool(hosts, owner)
    leaving = await a_member(managers, "ajax", Role.ADMIN)
    issued = await hosts.issue_enrollment_token(leaving, pool.id, BATCH)
    await managers.tenancy.members.remove_member(owner, leaving.user_id)
    with pytest.raises(CredentialExpired, match="issuer left"):
        await hosts.enroll_claimant(request(), issued.token, ClaimantEnrollment(name="node-1"))
    assert await hosts.get_claimants(owner, pool.id) == ()


async def test_a_revoked_or_expired_claimant_credential_is_refused(
    managers: Managers, hosts: HostsManagerImpl, clock: Clock
) -> None:
    owner = await an_owner(managers, "ajax")
    pool = await a_batch_pool(hosts, owner)

    expiring = await a_node(hosts, owner, pool, "node-1")
    clock.advance(OPTIONS.credential_ttl)
    with pytest.raises(CredentialExpired, match="batch credential expired"):
        await identity_of(hosts, expiring)

    revoked = await a_node(hosts, owner, pool, "node-2")
    in_flight = await identity_of(hosts, revoked)
    await managers.work.enqueue(owner, a_render(owner, pool.id))
    stored = await hosts.revoke_claimant(owner, revoked.claimant_id)
    assert stored.kind == BATCH and stored.revoked_at is not None
    with pytest.raises(CredentialExpired, match="batch revoked"):
        await identity_of(hosts, revoked)
    with pytest.raises(CredentialExpired, match="batch revoked"):
        await hosts.claim_as(request(), in_flight)
    # A product's claimant is revoked by its own call, never through a host's.
    with pytest.raises(NotFound):
        await hosts.revoke_host(owner, revoked.claimant_id)

    # A rotated credential presented past its grace means two machines hold
    # it: refused, and the claimant and every credential it holds end.
    copied = await a_node(hosts, owner, pool, "node-3")
    rotated = await hosts.rotate(request(), await identity_of(hosts, copied))
    clock.advance(OPTIONS.rotation_grace)
    with pytest.raises(CredentialExpired, match="rotated already"):
        await identity_of(hosts, copied)
    with pytest.raises(CredentialExpired):
        await hosts.authenticate_claimant(request(), rotated.credential)
