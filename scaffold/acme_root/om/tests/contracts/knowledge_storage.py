"""The knowledge storage contract: a tenant's entries by their state, each
change conditioned on the version read. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.knowledge.storage import KnowledgeStorageInterface
from acme.om.knowledge.types.knowledge import Knowledge, KnowledgeStatus

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_entry", "read_entry", "read_entries", "update_entry", "purge_tenant"}
)
"""Every method of `KnowledgeStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_entry(status: KnowledgeStatus = KnowledgeStatus.SUGGESTED) -> Knowledge:
    now = utcnow()
    actor = new_id()
    return Knowledge(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        title="the lab's flaky camera",
        trigger=("camera",),
        text="The camera on station 3 drops frames under load; rerun once.",
        status=status,
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
