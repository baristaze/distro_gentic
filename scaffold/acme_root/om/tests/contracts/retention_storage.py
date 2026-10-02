"""The retention storage contract: a tenant's policy, written once and then
by a compare-and-set; a session's snapshot, written once and then by a
compare-and-set; and the sweep's two reads across tenants. The cases named
in `CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, TenantMismatch, UniqueKeyTaken
from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention.keys import KeyDestruction
from acme.om.retention.storage import RetentionStorageInterface
from acme.om.retention.types.policy import ProjectRetention, RetentionPolicy, TenantRetention
from acme.om.retention.types.snapshot import SessionRetention

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_policy",
        "create_snapshot",
        "purge_tenant",
        "read_policy",
        "read_snapshot",
        "write_policy",
        "write_snapshot",
    }
)
"""Every method of `RetentionStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""

WEEK = timedelta(days=7)
MONTH = timedelta(days=30)


def make_policy(version: int = 1, policy: RetentionPolicy | None = None) -> TenantRetention:
    now, by = utcnow(), new_id()
    return TenantRetention(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        policy=policy or RetentionPolicy(content_lifetime=WEEK, shape_lifetime=MONTH),
        projects=(
            ProjectRetention(
                project_id=new_id(),
                policy=RetentionPolicy(storage_mode=StorageMode.MEMORY_ONLY),
            ),
        ),
        version=version,
    )


def make_snapshot(
    session_id: UUID | None = None,
    *,
    taken_at: datetime | None = None,
    policy_version: int = 1,
    content: timedelta | None = WEEK,
    shape: timedelta | None = MONTH,
) -> SessionRetention:
    taken = taken_at or utcnow()
    return SessionRetention(
        id=new_id(),
        created_at=taken,
        session_id=session_id or new_id(),
        policy=RetentionPolicy(content_lifetime=content, shape_lifetime=shape),
        policy_version=policy_version,
        at_rest=True,
        content_expires_at=None if content is None else taken + content,
        shape_expires_at=None if shape is None else taken + shape,
    )


def moved(snapshot: SessionRetention, **update: object) -> SessionRetention:
    return SessionRetention.model_validate(
        {**snapshot.model_dump(), **update, "version": snapshot.version + 1}
    )


class RetentionStorageContract:
    @pytest.fixture
    def storage(self) -> RetentionStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    # The tenant's policy.

    async def test_a_policy_is_written_once_and_then_by_its_version(
        self, storage: RetentionStorageInterface
    ) -> None:
        org = new_id()
        first = make_policy()
        assert await storage.create_policy(org, first, ())
        assert await storage.read_policy(org) == first
        assert not await storage.create_policy(org, first, ()), "a retry lands nothing"
        with pytest.raises(UniqueKeyTaken):
            await storage.create_policy(org, make_policy(), ())
        second = first.model_copy(update={"policy": RetentionPolicy(), "version": 2})
        await storage.write_policy(org, second, 1, ())
        assert await storage.read_policy(org) == second
        with pytest.raises(PreconditionFailed):
            await storage.write_policy(org, second.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_policy(org) == second

    async def test_another_tenants_policy_is_never_reached(
        self, storage: RetentionStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        policy = make_policy()
        assert await storage.create_policy(org, policy, ())
        assert await storage.read_policy(other) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_policy(other, policy.model_copy(update={"version": 2}), 1, ())
        assert not await storage.create_policy(other, policy, ()), "the id is another tenant's"
        assert await storage.read_policy(other) is None
        assert await storage.read_policy(org) == policy

    # A session's snapshot.

    async def test_a_snapshot_is_written_once_and_then_by_its_version(
        self, storage: RetentionStorageInterface
    ) -> None:
        org = new_id()
        first = make_snapshot()
        assert await storage.create_snapshot(org, first) == first
        again = make_snapshot(first.session_id, content=None, shape=None)
        assert await storage.create_snapshot(org, again) == first, "the first stands"
        assert await storage.read_snapshot(org, first.session_id) == first
        report = KeyDestruction(
            service="keys=local", key="k", destroyed_at=utcnow(), receipt=str(new_id())
        )
        done = moved(first, content_expired_at=utcnow(), destruction=report)
        assert await storage.write_snapshot(org, done, 1)
        assert await storage.read_snapshot(org, first.session_id) == done
        assert not await storage.write_snapshot(org, moved(done), 1), "the version moved"
        assert await storage.read_snapshot(org, first.session_id) == done

    async def test_another_tenants_snapshot_is_never_reached(
        self, storage: RetentionStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        snapshot = make_snapshot()
        await storage.create_snapshot(org, snapshot)
        assert await storage.read_snapshot(other, snapshot.session_id) is None
        assert not await storage.write_snapshot(other, moved(snapshot), 1)
        with pytest.raises(TenantMismatch):
            await storage.create_snapshot(other, snapshot)
        assert await storage.read_snapshot(other, snapshot.session_id) is None
        assert await storage.read_snapshot(org, snapshot.session_id) == snapshot

    # The sweep's reads across tenants.

    async def test_the_sweep_reads_the_snapshots_behind_their_tenants_policy(
        self, storage: RetentionStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        policy = make_policy(version=1)
        assert await storage.create_policy(org, policy, ())
        level = make_snapshot(policy_version=1)
        behind = make_snapshot(policy_version=0)
        no_policy = make_snapshot(policy_version=0)
        for snapshot in (level, behind):
            await storage.create_snapshot(org, snapshot)
        await storage.create_snapshot(other, no_policy)
        found = await storage.read_behind(100)
        assert [(o, s.id, p.id) for o, s, p in found if o in (org, other)] == [
            (org, behind.id, policy.id)
        ]
        assert len(await storage.read_behind(1)) == 1

    async def test_the_sweep_reads_what_has_expired_and_is_not_taken_up(
        self, storage: RetentionStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        now = utcnow()
        content = make_snapshot(taken_at=now - WEEK - timedelta(minutes=1))
        shape = moved(
            make_snapshot(taken_at=now - MONTH - timedelta(minutes=1)),
            content_expired_at=now - MONTH,
        )
        taken_up = moved(
            make_snapshot(taken_at=now - MONTH - timedelta(minutes=1)),
            content_expired_at=now - MONTH,
            shape_expired_at=now,
        )
        young = make_snapshot(taken_at=now)
        forever = make_snapshot(taken_at=now - MONTH * 12, content=None, shape=None)
        waiting = moved(
            make_snapshot(taken_at=now - MONTH * 2), next_attempt_at=now + timedelta(minutes=5)
        )
        retried = moved(
            make_snapshot(taken_at=now - MONTH * 2), next_attempt_at=now - timedelta(minutes=5)
        )
        for snapshot in (content, shape, taken_up, waiting, retried):
            await storage.create_snapshot(org, snapshot)
        for snapshot in (young, forever):
            await storage.create_snapshot(other, snapshot)
        found = await storage.read_due(now, 100)
        ours = {(o, s.id) for o, s in found if o in (org, other)}
        assert ours == {(org, content.id), (org, shape.id), (org, retried.id)}
        assert len(await storage.read_due(now, 1)) == 1

    # The purge of a tenant past its retention.

    async def test_a_purge_takes_its_tenants_rows_and_no_other(
        self, storage: RetentionStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        assert await storage.create_policy(org, make_policy(), ())
        assert await storage.create_policy(other, make_policy(), ())
        mine = [make_snapshot() for _ in range(3)]
        for snapshot in mine:
            await storage.create_snapshot(org, snapshot)
        theirs = make_snapshot()
        await storage.create_snapshot(other, theirs)
        assert await storage.purge_tenant(org, 2) == 2
        assert await storage.purge_tenant(org, 10) == 2, "the last snapshot, then the policy"
        assert await storage.purge_tenant(org, 10) == 0
        assert await storage.read_policy(org) is None
        assert await storage.read_policy(other) is not None
        assert await storage.read_snapshot(other, theirs.session_id) == theirs
