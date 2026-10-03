"""The knowledge storage contract: a tenant's entries by their state, each
change conditioned on the version read, and the reviewed ones a session of
a project reaches, whole or by slug: its project's and those of no
project, never another project's. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.knowledge.rules import slug_of
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_entry",
        "read_entry",
        "read_entries",
        "read_reachable",
        "read_by_slug",
        "update_entry",
        "purge_tenant",
    }
)
"""Every method of `KnowledgeStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_entry(
    status: KnowledgeStatus = KnowledgeStatus.SUGGESTED, project_id: UUID | None = None
) -> Knowledge:
    now = utcnow()
    actor = new_id()
    entry_id = new_id()
    title = "the flaky staging database"
    return Knowledge(
        id=entry_id,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        title=title,
        trigger=("database",),
        text="The staging database drops connections under load; rerun once.",
        status=status,
        reviewed_by=actor if status is KnowledgeStatus.REVIEWED else None,
        project_id=project_id,
        slug=slug_of(title, entry_id),
    )


def reviewed(entry: Knowledge) -> Knowledge:
    return entry.model_copy(
        update={
            "status": KnowledgeStatus.REVIEWED,
            "reviewed_by": new_id(),
            "version": entry.version + 1,
        }
    )


class KnowledgeStorageContract:
    async def test_an_entry_moves_by_its_version(self, storage: KnowledgeStorageInterface) -> None:
        org = new_id()
        entry = make_entry()
        assert await storage.create_entry(org, entry, ())
        assert not await storage.create_entry(org, entry, ())
        assert await storage.read_entries(org, KnowledgeStatus.REVIEWED, None, 10) == []
        kept = reviewed(entry)
        await storage.update_entry(org, kept, ())
        with pytest.raises(PreconditionFailed):
            await storage.update_entry(org, kept, ())
        assert await storage.read_entry(org, entry.id) == kept
        assert await storage.read_entries(org, KnowledgeStatus.REVIEWED, None, 10) == [kept]
        assert await storage.read_entries(org, KnowledgeStatus.SUGGESTED, None, 10) == []

    async def test_create_entry_in_another_tenant_is_not_read_here(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        entry = make_entry()
        await storage.create_entry(org_a, entry, ())
        assert not await storage.create_entry(org_b, entry, ())
        assert await storage.read_entry(org_b, entry.id) is None

    async def test_read_entry_of_another_tenant_finds_nothing(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        entry = make_entry()
        await storage.create_entry(new_id(), entry, ())
        assert await storage.read_entry(new_id(), entry.id) is None

    async def test_read_entries_of_another_tenant_finds_nothing(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        await storage.create_entry(new_id(), make_entry(KnowledgeStatus.REVIEWED), ())
        assert await storage.read_entries(new_id(), KnowledgeStatus.REVIEWED, None, 10) == []

    async def test_update_entry_of_another_tenant_changes_nothing(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        org = new_id()
        entry = make_entry()
        await storage.create_entry(org, entry, ())
        with pytest.raises(PreconditionFailed):
            await storage.update_entry(new_id(), reviewed(entry), ())
        assert await storage.read_entry(org, entry.id) == entry

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_entry(org_a, make_entry(), ())
        kept = make_entry()
        await storage.create_entry(org_b, kept, ())
        assert await storage.purge_tenant(org_a, 10) == 1
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_entry(org_b, kept.id) == kept

    async def test_a_session_reaches_its_projects_entries_and_the_tenants_alone(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        org, ours, theirs = new_id(), new_id(), new_id()
        own = make_entry(KnowledgeStatus.REVIEWED, ours)
        whole = make_entry(KnowledgeStatus.REVIEWED)
        other = make_entry(KnowledgeStatus.REVIEWED, theirs)
        waiting = make_entry(KnowledgeStatus.SUGGESTED, ours)
        rejected = make_entry(KnowledgeStatus.REJECTED, ours)
        for entry in (own, whole, other, waiting, rejected):
            assert await storage.create_entry(org, entry, ())
        assert await storage.read_reachable(org, ours, None, 10) == sorted(
            (own, whole), key=lambda e: e.id
        )
        assert await storage.read_reachable(org, None, None, 10) == [whole]
        first = min(own.id, whole.id)
        assert [e.id for e in await storage.read_reachable(org, ours, first, 10)] == [
            max(own.id, whole.id)
        ]
        assert [e.id for e in await storage.read_reachable(org, ours, None, 1)] == [first]
        for entry, reached in (
            (own, True),
            (whole, True),
            (other, False),
            (waiting, False),
            (rejected, False),
        ):
            assert entry.slug is not None
            found = await storage.read_by_slug(org, ours, entry.slug)
            assert (found == entry) is reached, entry.status
        assert own.slug is not None and whole.slug is not None
        assert await storage.read_by_slug(org, None, own.slug) is None
        assert await storage.read_by_slug(org, None, whole.slug) == whole

    async def test_read_reachable_of_another_tenant_finds_nothing(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        project = new_id()
        await storage.create_entry(new_id(), make_entry(KnowledgeStatus.REVIEWED, project), ())
        await storage.create_entry(new_id(), make_entry(KnowledgeStatus.REVIEWED), ())
        assert await storage.read_reachable(new_id(), project, None, 10) == []
        assert await storage.read_reachable(new_id(), None, None, 10) == []

    async def test_read_by_slug_of_another_tenant_finds_nothing(
        self, storage: KnowledgeStorageInterface
    ) -> None:
        project = new_id()
        entry = make_entry(KnowledgeStatus.REVIEWED, project)
        await storage.create_entry(new_id(), entry, ())
        assert entry.slug is not None
        assert await storage.read_by_slug(new_id(), project, entry.slug) is None
