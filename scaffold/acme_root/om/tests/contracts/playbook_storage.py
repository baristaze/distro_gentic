"""The playbooks storage contract: every published version, written once,
and the playbooks each session invoked. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import UniqueKeyTaken
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import Playbook, PlaybookGate, PlaybookInvocation
from acme.om.tools.types.policy import Decision

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_playbook",
        "read_playbook",
        "read_latest",
        "create_invocation",
        "read_invocations",
        "purge_tenant",
    }
)
"""Every method of `PlaybookStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_playbook(version: int = 1, name: str = "release-a-build") -> Playbook:
    return Playbook(
        id=new_id(),
        created_at=utcnow(),
        name=name,
        version=version,
        description="Cut a release build and hand it to the line.",
        body="## Steps\n\n1. Build.\n2. Ask before you publish.",
        gates=(PlaybookGate(tool="publish", decision=Decision.APPROVE),),
        published_by=new_id(),
    )


def make_invocation(playbook: Playbook, session_id: UUID | None = None) -> PlaybookInvocation:
    return PlaybookInvocation(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id or new_id(),
        playbook_id=playbook.id,
        name=playbook.name,
        version=playbook.version,
        invoked_by=new_id(),
    )


class PlaybookStorageContract:
    async def test_versions_are_written_once_and_the_latest_reads_back(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org = new_id()
        first, second = make_playbook(1), make_playbook(2)
        assert await storage.create_playbook(org, first, ())
        assert not await storage.create_playbook(org, first, ())
        assert await storage.create_playbook(org, second, ())
        with pytest.raises(UniqueKeyTaken):
            await storage.create_playbook(org, make_playbook(2), ())
        assert await storage.read_latest(org, first.name) == second
        assert await storage.read_playbook(org, first.id) == first
        assert await storage.read_latest(org, "other") is None

    async def test_a_session_invokes_a_version_once(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org = new_id()
        playbook = make_playbook()
        await storage.create_playbook(org, playbook, ())
        first = make_invocation(playbook)
        assert await storage.create_invocation(org, first) == first
        again = make_invocation(playbook, first.session_id)
        assert await storage.create_invocation(org, again) == first
        assert await storage.read_invocations(org, first.session_id, 10) == [first]

    async def test_create_playbook_in_another_tenant_is_its_own(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_playbook(org_a, make_playbook(1), ())
        theirs = make_playbook(1)
        assert await storage.create_playbook(org_b, theirs, ())
        assert await storage.read_latest(org_b, theirs.name) == theirs

    async def test_read_playbook_of_another_tenant_finds_nothing(
        self, storage: PlaybookStorageInterface
    ) -> None:
        playbook = make_playbook()
        await storage.create_playbook(new_id(), playbook, ())
        assert await storage.read_playbook(new_id(), playbook.id) is None

    async def test_read_latest_of_another_tenant_finds_nothing(
        self, storage: PlaybookStorageInterface
    ) -> None:
        playbook = make_playbook()
        await storage.create_playbook(new_id(), playbook, ())
        assert await storage.read_latest(new_id(), playbook.name) is None

    async def test_create_invocation_in_another_tenant_is_its_own(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        playbook = make_playbook()
        mine = make_invocation(playbook)
        await storage.create_invocation(org_a, mine)
        theirs = make_invocation(playbook, mine.session_id)
        assert await storage.create_invocation(org_b, theirs) == theirs
        assert await storage.read_invocations(org_a, mine.session_id, 10) == [mine]

    async def test_read_invocations_of_another_tenant_finds_nothing(
        self, storage: PlaybookStorageInterface
    ) -> None:
        invocation = make_invocation(make_playbook())
        await storage.create_invocation(new_id(), invocation)
        assert await storage.read_invocations(new_id(), invocation.session_id, 10) == []

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        playbook = make_playbook()
        await storage.create_playbook(org_a, playbook, ())
        await storage.create_invocation(org_a, make_invocation(playbook))
        kept = make_playbook()
        await storage.create_playbook(org_b, kept, ())
        assert await storage.purge_tenant(org_a, 10) == 2
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_latest(org_b, kept.name) == kept
