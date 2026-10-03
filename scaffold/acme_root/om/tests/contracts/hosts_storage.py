"""The hosts storage contract: pools, enrollment tokens, hosts with their
credentials, and session placements. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.types.credential import EnrollmentToken, HostCredential, Rotation
from acme.om.hosts.types.host import Advertisement, Host, HostReport, IsolationMode
from acme.om.hosts.types.placement import SessionPlacement
from acme.om.hosts.types.pool import HostPool

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_pool",
        "read_pool",
        "read_pools",
        "create_enrollment_token",
        "revoke_enrollment_token",
        "enroll_host",
        "read_host",
        "read_hosts",
        "rotate_credential",
        "mark_seen",
        "revoke_host",
        "read_placement",
        "write_placement",
        "purge_tenant",
    }
)
"""Every method of `HostsStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""

ADVERTISED = Advertisement(
    os="Linux 6.8",
    shell="/bin/bash",
    capabilities=("git",),
    isolation_modes=(IsolationMode.CONTAINER,),
)


def make_pool(name: str = "lab") -> HostPool:
    now = utcnow()
    actor = new_id()
    return HostPool(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        name=name,
        region="eu-west",
        labels=("gpu",),
    )


def make_token(pool_id: UUID) -> EnrollmentToken:
    now = utcnow()
    actor = new_id()
    return EnrollmentToken(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        pool_id=pool_id,
        digest=f"digest-{new_id()}",
        expires_at=now + timedelta(days=1),
    )


def make_host(pool_id: UUID) -> Host:
    now = utcnow()
    actor = new_id()
    return Host(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        pool_id=pool_id,
        name="host-7",
        enrolled_with=new_id(),
        advertisement=ADVERTISED,
        exec_version=1,
        last_seen_at=now,
    )


def make_credential(host_id: UUID, lives: timedelta = timedelta(hours=1)) -> HostCredential:
    now = utcnow()
    return HostCredential(
        id=new_id(),
        created_at=now,
        host_id=host_id,
        digest=f"digest-{new_id()}",
        expires_at=now + lives,
    )


def make_placement(session_id: UUID, pool_id: UUID | None) -> SessionPlacement:
    now = utcnow()
    actor = new_id()
    return SessionPlacement(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        session_id=session_id,
        pool_id=pool_id,
    )


class HostsStorageContract:
    @pytest.fixture
    def storage(self) -> HostsStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def enrolled(
        self, storage: HostsStorageInterface, org: UUID
    ) -> tuple[Host, HostCredential]:
        host = make_host(new_id())
        credential = make_credential(host.id)
        await storage.enroll_host(org, host, credential, ())
        return host, credential

    async def test_count_hosts_answers_every_tenants_unrevoked_hosts_by_state(
        self, storage: HostsStorageInterface
    ) -> None:
        """The platform's gauge of hosts: every tenant's hosts not revoked,
        by whether they called since the cut and read at or above the floor.
        The read spans every tenant, so the case reads what its own rows add."""
        now = utcnow()
        cut = now - timedelta(minutes=2)
        before = await storage.count_hosts(cut, 2)
        first, second = new_id(), new_id()
        rows = (
            (first, make_host(new_id()).model_copy(update={"exec_version": 2})),
            (second, make_host(new_id()).model_copy(update={"exec_version": 3})),
            (
                first,
                make_host(new_id()).model_copy(
                    update={"exec_version": 2, "last_seen_at": now - timedelta(minutes=5)}
                ),
            ),
            (second, make_host(new_id())),
            (first, make_host(new_id()).model_copy(update={"revoked_at": now})),
        )
        for org, host in rows:
            await storage.enroll_host(org, host, make_credential(host.id), ())
        after = await storage.count_hosts(cut, 2)
        added = {key: after.get(key, 0) - before.get(key, 0) for key in after}
        assert {key: n for key, n in added.items() if n} == {
            (True, True): 2,
            (False, True): 1,
            (True, False): 1,
        }

    # Pools.

    async def test_a_pool_round_trips(self, storage: HostsStorageInterface) -> None:
        org = new_id()
        first, second = make_pool("a"), make_pool("b")
        assert await storage.create_pool(org, first, ())
        assert await storage.create_pool(org, second, ())
        assert not await storage.create_pool(org, first.model_copy(update={"name": "c"}), ())
        assert await storage.read_pool(org, first.id) == first
        assert await storage.read_pools(org, 10) == sorted([first, second], key=lambda p: p.id)
        assert len(await storage.read_pools(org, 1)) == 1

    async def test_create_pool_under_another_tenant_is_not_read_here(
        self, storage: HostsStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        pool = make_pool()
        assert await storage.create_pool(org_a, pool, ())
        assert not await storage.create_pool(org_b, pool, ())
        assert await storage.read_pool(org_b, pool.id) is None

    async def test_read_pool_and_pools_of_another_tenant_find_nothing(
        self, storage: HostsStorageInterface
    ) -> None:
        pool = make_pool()
        assert await storage.create_pool(new_id(), pool, ())
        other = new_id()
        assert await storage.read_pool(other, pool.id) is None
        assert await storage.read_pools(other, 10) == []

    # Enrollment tokens.

    async def test_a_token_is_found_by_its_digest_with_its_tenant(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        token = make_token(new_id())
        assert await storage.create_enrollment_token(org, token, ())
        assert await storage.read_enrollment_token_by_digest(token.digest) == (org, token)
        assert await storage.read_enrollment_token_by_digest("digest-unknown") is None

    async def test_a_tokens_digest_is_unique_across_tenants(
        self, storage: HostsStorageInterface
    ) -> None:
        token = make_token(new_id())
        assert await storage.create_enrollment_token(new_id(), token, ())
        twin = make_token(new_id()).model_copy(update={"digest": token.digest})
        with pytest.raises(UniqueKeyTaken):
            await storage.create_enrollment_token(new_id(), twin, ())

    async def test_create_enrollment_token_under_another_tenant_is_not_found_there(
        self, storage: HostsStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        token = make_token(new_id())
        assert await storage.create_enrollment_token(org_a, token, ())
        assert not await storage.create_enrollment_token(org_b, token, ())
        assert await storage.read_enrollment_token_by_digest(token.digest) == (org_a, token)

    async def test_revoke_enrollment_token_ends_it_once(
        self, storage: HostsStorageInterface
    ) -> None:
        org, by = new_id(), new_id()
        token = make_token(new_id())
        assert await storage.create_enrollment_token(org, token, ())
        at = utcnow()
        revoked = await storage.revoke_enrollment_token(org, token.id, at, by, ())
        assert revoked is not None
        assert (revoked.revoked_at, revoked.revoked_by) == (at, by)
        again = await storage.revoke_enrollment_token(
            org, token.id, at + timedelta(1), new_id(), ()
        )
        assert again == revoked
        assert await storage.read_enrollment_token_by_digest(token.digest) == (org, revoked)

    async def test_revoke_enrollment_token_of_another_tenant_changes_nothing(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        token = make_token(new_id())
        assert await storage.create_enrollment_token(org, token, ())
        assert (
            await storage.revoke_enrollment_token(new_id(), token.id, utcnow(), new_id(), ())
            is None
        )
        assert await storage.read_enrollment_token_by_digest(token.digest) == (org, token)

    # Hosts and their credentials.

    async def test_a_host_is_found_by_its_credential_with_its_tenant(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, credential = await self.enrolled(storage, org)
        assert await storage.read_host(org, host.id) == host
        assert await storage.read_hosts(org, host.pool_id, 10) == [host]
        assert await storage.read_hosts(org, new_id(), 10) == []
        found = await storage.read_host_by_credential_digest(credential.digest)
        assert found == (org, credential, host)
        assert await storage.read_host_by_credential_digest("digest-unknown") is None

    async def test_a_credentials_digest_is_unique_across_tenants(
        self, storage: HostsStorageInterface
    ) -> None:
        _, credential = await self.enrolled(storage, new_id())
        host = make_host(new_id())
        twin = make_credential(host.id).model_copy(update={"digest": credential.digest})
        with pytest.raises(UniqueKeyTaken):
            await storage.enroll_host(new_id(), host, twin, ())
        assert await storage.read_host(new_id(), host.id) is None

    async def test_enroll_host_under_another_tenant_is_not_read_here(
        self, storage: HostsStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        host, credential = await self.enrolled(storage, org_a)
        assert await storage.read_host(org_b, host.id) is None
        assert await storage.read_hosts(org_b, host.pool_id, 10) == []
        found = await storage.read_host_by_credential_digest(credential.digest)
        assert found is not None and found[0] == org_a

    async def test_rotate_credential_mints_the_next_and_ends_the_last(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, credential = await self.enrolled(storage, org)
        now = utcnow()
        minted = make_credential(host.id)
        grace_end = now + timedelta(minutes=1)
        rotated = await storage.rotate_credential(org, credential.id, now, grace_end, minted)
        assert rotated is Rotation.ROTATED
        old = await storage.read_host_by_credential_digest(credential.digest)
        assert old is not None and (old[1].expires_at, old[1].rotated_at) == (grace_end, now)
        assert await storage.read_host_by_credential_digest(minted.digest) == (org, minted, host)
        # The next rotation, inside the last one's grace, ends that one at
        # once, and a later end never stretches a sooner one.
        at = now + timedelta(seconds=30)
        third = make_credential(host.id)
        rotated = await storage.rotate_credential(
            org, minted.id, at, at + timedelta(hours=5), third
        )
        assert rotated is Rotation.ROTATED
        first = await storage.read_host_by_credential_digest(credential.digest)
        assert first is not None and first[1].expires_at == at
        second = await storage.read_host_by_credential_digest(minted.digest)
        assert second is not None
        assert (second[1].expires_at, second[1].rotated_at) == (minted.expires_at, at)
        assert await storage.read_host_by_credential_digest(third.digest) == (org, third, host)

    async def test_a_credential_rotates_once(self, storage: HostsStorageInterface) -> None:
        org = new_id()
        host, credential = await self.enrolled(storage, org)
        now = utcnow()
        grace_end = now + timedelta(minutes=1)
        first = await storage.rotate_credential(
            org, credential.id, now, grace_end, make_credential(host.id)
        )
        assert first is Rotation.ROTATED
        copy = make_credential(host.id)
        again = await storage.rotate_credential(org, credential.id, now, grace_end, copy)
        assert again is Rotation.REUSED
        assert await storage.read_host_by_credential_digest(copy.digest) is None

    async def test_rotate_credential_of_another_tenant_or_host_changes_nothing(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, credential = await self.enrolled(storage, org)
        now = utcnow()
        minted = make_credential(host.id)
        missing = await storage.rotate_credential(new_id(), credential.id, now, now, minted)
        assert missing is Rotation.MISSING
        stranger = make_credential(new_id())
        missing = await storage.rotate_credential(org, credential.id, now, now, stranger)
        assert missing is Rotation.MISSING
        assert await storage.read_host_by_credential_digest(minted.digest) is None
        assert await storage.read_host_by_credential_digest(stranger.digest) is None
        found = await storage.read_host_by_credential_digest(credential.digest)
        assert found == (org, credential, host)

    async def test_mark_seen_keeps_what_the_host_stated(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, _ = await self.enrolled(storage, org)
        at = utcnow() + timedelta(seconds=5)
        report = HostReport(
            advertisement=ADVERTISED.model_copy(update={"isolation_modes": ()}), exec_version=2
        )
        assert await storage.mark_seen(org, host.id, at, report)
        seen = await storage.read_host(org, host.id)
        assert seen is not None
        assert (seen.last_seen_at, seen.advertisement, seen.exec_version) == (
            at,
            report.advertisement,
            2,
        )

    async def test_mark_seen_of_another_tenant_changes_nothing(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, _ = await self.enrolled(storage, org)
        report = HostReport(advertisement=ADVERTISED, exec_version=9)
        assert not await storage.mark_seen(new_id(), host.id, utcnow(), report)
        assert await storage.read_host(org, host.id) == host

    async def test_revoke_host_ends_it_and_its_credentials(
        self, storage: HostsStorageInterface
    ) -> None:
        org, by = new_id(), new_id()
        host, credential = await self.enrolled(storage, org)
        at = utcnow()
        revoked = await storage.revoke_host(org, host.id, at, by, ())
        assert revoked is not None and (revoked.revoked_at, revoked.revoked_by) == (at, by)
        found = await storage.read_host_by_credential_digest(credential.digest)
        assert found is not None and found[1].expires_at == at and found[2] == revoked
        again = await storage.revoke_host(org, host.id, at + timedelta(1), new_id(), ())
        assert again == revoked

    async def test_revoke_host_of_another_tenant_changes_nothing(
        self, storage: HostsStorageInterface
    ) -> None:
        org = new_id()
        host, credential = await self.enrolled(storage, org)
        assert await storage.revoke_host(new_id(), host.id, utcnow(), new_id(), ()) is None
        assert await storage.read_host_by_credential_digest(credential.digest) == (
            org,
            credential,
            host,
        )

    # Placements.

    async def test_write_placement_is_a_compare_and_set(
        self, storage: HostsStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        placed = make_placement(session, new_id())
        await storage.write_placement(org, placed, 0, ())
        assert await storage.read_placement(org, session) == placed
        with pytest.raises(PreconditionFailed):
            await storage.write_placement(org, make_placement(session, None), 0, ())
        moved = placed.model_copy(update={"pool_id": None, "version": 2})
        await storage.write_placement(org, moved, 1, ())
        assert await storage.read_placement(org, session) == moved
        with pytest.raises(PreconditionFailed):
            await storage.write_placement(org, moved.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_placement(org, session) == moved

    async def test_placement_of_another_tenant_is_neither_read_nor_written(
        self, storage: HostsStorageInterface
    ) -> None:
        org_a, org_b, session = new_id(), new_id(), new_id()
        placed = make_placement(session, new_id())
        await storage.write_placement(org_a, placed, 0, ())
        assert await storage.read_placement(org_b, session) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_placement(
                org_b, placed.model_copy(update={"pool_id": None, "version": 2}), 1, ()
            )
        assert await storage.read_placement(org_a, session) == placed

    # Purge.

    async def test_purge_tenant_takes_the_tenants_rows_and_no_other(
        self, storage: HostsStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        for org in (gone, kept):
            pool = make_pool()
            assert await storage.create_pool(org, pool, ())
            assert await storage.create_enrollment_token(org, make_token(pool.id), ())
            await self.enrolled(storage, org)
            await storage.write_placement(org, make_placement(new_id(), pool.id), 0, ())
        kept_pools = await storage.read_pools(kept, 10)
        assert await storage.purge_tenant(gone, 100) == 5
        assert await storage.purge_tenant(gone, 100) == 0
        assert await storage.read_pools(gone, 10) == []
        assert await storage.read_pools(kept, 10) == kept_pools
