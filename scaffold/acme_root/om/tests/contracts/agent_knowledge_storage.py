"""The agent knowledge storage contract: a tenant's entries by their state, each
change conditioned on the version read, with the findings read in it, and
the reviewed ones a session of an agent project reaches, whole or by slug: its
agent project's and those of no agent project, never another agent project's; and the
versions each session recalled, one recall of an entry a session. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from uuid import UUID

import pytest

from acme.om.agent_knowledge.rules import slug_of
from acme.om.agent_knowledge.storage import AgentKnowledgeStorageInterface
from acme.om.agent_knowledge.types.agent_knowledge import (
    AgentKnowledge,
    AgentKnowledgeRecall,
    AgentKnowledgeStatus,
)
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.levers.types.lever import LeverCheck, LeverFinding

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_entry",
        "read_entry",
        "read_entries",
        "read_reachable",
        "read_by_slug",
        "update_entry",
        "create_recalls",
        "read_recalls",
        "purge_tenant",
    }
)
"""Every method of `AgentKnowledgeStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_entry(
    status: AgentKnowledgeStatus = AgentKnowledgeStatus.SUGGESTED,
    agent_project_id: UUID | None = None,
) -> AgentKnowledge:
    now = utcnow()
    actor = new_id()
    entry_id = new_id()
    title = "the flaky staging database"
    return AgentKnowledge(
        id=entry_id,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        title=title,
        trigger=("database",),
        text="The staging database drops connections under load; rerun once.",
        status=status,
        reviewed_by=actor if status is AgentKnowledgeStatus.REVIEWED else None,
        agent_project_id=agent_project_id,
        slug=slug_of(title, entry_id),
        findings=(
            LeverFinding(
                check=LeverCheck.REPEATED_PHRASE,
                detail="“staging database” comes 5 times, past 4",
                excerpt="staging database",
            ),
        ),
    )


def make_recall(session_id: UUID, entry: AgentKnowledge) -> AgentKnowledgeRecall:
    return AgentKnowledgeRecall(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id,
        entry_id=entry.id,
        version=entry.version,
    )


def reviewed(entry: AgentKnowledge) -> AgentKnowledge:
    return entry.model_copy(
        update={
            "status": AgentKnowledgeStatus.REVIEWED,
            "reviewed_by": new_id(),
            "version": entry.version + 1,
        }
    )


class AgentKnowledgeStorageContract:
    async def test_an_entry_moves_by_its_version(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org = new_id()
        entry = make_entry()
        assert await storage.create_entry(org, entry, ())
        assert not await storage.create_entry(org, entry, ())
        assert await storage.read_entries(org, AgentKnowledgeStatus.REVIEWED, None, 10) == []
        kept = reviewed(entry)
        await storage.update_entry(org, kept, ())
        with pytest.raises(PreconditionFailed):
            await storage.update_entry(org, kept, ())
        assert await storage.read_entry(org, entry.id) == kept
        assert await storage.read_entries(org, AgentKnowledgeStatus.REVIEWED, None, 10) == [kept]
        assert await storage.read_entries(org, AgentKnowledgeStatus.SUGGESTED, None, 10) == []

    async def test_an_entry_never_checked_reads_apart_from_one_checked_and_clean(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org = new_id()
        unchecked = make_entry().model_copy(update={"findings": None})
        clean = make_entry().model_copy(update={"findings": ()})
        for entry in (unchecked, clean):
            assert await storage.create_entry(org, entry, ())
        assert (await storage.read_entry(org, unchecked.id)) == unchecked
        assert (await storage.read_entry(org, clean.id)) == clean

    async def test_create_entry_in_another_tenant_is_not_read_here(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        entry = make_entry()
        await storage.create_entry(org_a, entry, ())
        assert not await storage.create_entry(org_b, entry, ())
        assert await storage.read_entry(org_b, entry.id) is None

    async def test_read_entry_of_another_tenant_finds_nothing(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        entry = make_entry()
        await storage.create_entry(new_id(), entry, ())
        assert await storage.read_entry(new_id(), entry.id) is None

    async def test_read_entries_of_another_tenant_finds_nothing(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        await storage.create_entry(new_id(), make_entry(AgentKnowledgeStatus.REVIEWED), ())
        assert await storage.read_entries(new_id(), AgentKnowledgeStatus.REVIEWED, None, 10) == []

    async def test_update_entry_of_another_tenant_changes_nothing(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org = new_id()
        entry = make_entry()
        await storage.create_entry(org, entry, ())
        with pytest.raises(PreconditionFailed):
            await storage.update_entry(new_id(), reviewed(entry), ())
        assert await storage.read_entry(org, entry.id) == entry

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        gone = make_entry()
        await storage.create_entry(org_a, gone, ())
        await storage.create_recalls(org_a, (make_recall(new_id(), gone),))
        kept = make_entry()
        await storage.create_entry(org_b, kept, ())
        recall = make_recall(new_id(), kept)
        await storage.create_recalls(org_b, (recall,))
        assert await storage.purge_tenant(org_a, 10) == 2
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_entry(org_b, kept.id) == kept
        assert await storage.read_recalls(org_b, recall.session_id, 10) == [recall]

    async def test_a_session_recalls_an_entry_once_at_the_version_it_read(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org, session_id = new_id(), new_id()
        first, second = (
            make_entry(AgentKnowledgeStatus.REVIEWED),
            make_entry(AgentKnowledgeStatus.REVIEWED),
        )
        recalls = (make_recall(session_id, first), make_recall(session_id, second))
        await storage.create_recalls(org, recalls)
        await storage.create_recalls(org, (make_recall(session_id, reviewed(first)),))
        await storage.create_recalls(org, ())
        assert await storage.read_recalls(org, session_id, 10) == sorted(
            recalls, key=lambda r: (r.created_at, r.id)
        )
        assert len(await storage.read_recalls(org, session_id, 1)) == 1
        assert await storage.read_recalls(org, new_id(), 10) == []

    async def test_create_recalls_in_another_tenant_is_not_read_here(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org, session_id = new_id(), new_id()
        await storage.create_recalls(new_id(), (make_recall(session_id, make_entry()),))
        assert await storage.read_recalls(org, session_id, 10) == []

    async def test_read_recalls_of_another_tenant_finds_nothing(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        session_id = new_id()
        await storage.create_recalls(new_id(), (make_recall(session_id, make_entry()),))
        assert await storage.read_recalls(new_id(), session_id, 10) == []

    async def test_a_session_reaches_its_agent_projects_entries_and_the_tenants_alone(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        org, ours, theirs = new_id(), new_id(), new_id()
        own = make_entry(AgentKnowledgeStatus.REVIEWED, ours)
        whole = make_entry(AgentKnowledgeStatus.REVIEWED)
        other = make_entry(AgentKnowledgeStatus.REVIEWED, theirs)
        waiting = make_entry(AgentKnowledgeStatus.SUGGESTED, ours)
        rejected = make_entry(AgentKnowledgeStatus.REJECTED, ours)
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
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        agent_project = new_id()
        await storage.create_entry(
            new_id(), make_entry(AgentKnowledgeStatus.REVIEWED, agent_project), ()
        )
        await storage.create_entry(new_id(), make_entry(AgentKnowledgeStatus.REVIEWED), ())
        assert await storage.read_reachable(new_id(), agent_project, None, 10) == []
        assert await storage.read_reachable(new_id(), None, None, 10) == []

    async def test_read_by_slug_of_another_tenant_finds_nothing(
        self, storage: AgentKnowledgeStorageInterface
    ) -> None:
        agent_project = new_id()
        entry = make_entry(AgentKnowledgeStatus.REVIEWED, agent_project)
        await storage.create_entry(new_id(), entry, ())
        assert entry.slug is not None
        assert await storage.read_by_slug(new_id(), agent_project, entry.slug) is None
