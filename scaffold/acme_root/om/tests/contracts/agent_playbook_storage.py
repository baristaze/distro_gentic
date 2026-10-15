"""The agent playbooks storage contract: every published version, written once
with the findings read in it, none on one never checked, the agent playbooks
each session invoked, and the versions pinned to kinds, one a kind in an
agent project and one for the tenant, never confused. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from uuid import UUID

import pytest

from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookGate,
    AgentPlaybookInvocation,
    AgentPlaybookPin,
)
from acme.om.base import new_id, utcnow
from acme.om.exceptions import TenantMismatch, UniqueKeyTaken
from acme.om.levers.types.lever import LeverCheck, LeverFinding
from acme.om.tools.types.policy import Decision

INTERFACE = AgentPlaybookStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_agent_playbook",
        "read_agent_playbook",
        "read_latest",
        "create_invocation",
        "read_invocations",
        "put_pin",
        "read_pin",
        "read_pins",
        "delete_pin",
        "purge_tenant",
    }
)
"""Every method of `AgentPlaybookStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_agent_playbook(version: int = 1, name: str = "release-a-build") -> AgentPlaybook:
    return AgentPlaybook(
        id=new_id(),
        created_at=utcnow(),
        name=name,
        version=version,
        description="Cut a release build and hand it to the line.",
        body="## Steps\n\n1. Build.\n2. Ask before you publish.",
        gates=(AgentPlaybookGate(tool="publish", decision=Decision.APPROVE),),
        published_by=new_id(),
        findings=(
            LeverFinding(
                check=LeverCheck.UNBOUNDED_RETRY,
                detail="“keep trying” with no stopping condition",
                excerpt="Keep trying the build until it is green.",
            ),
        ),
    )


def make_invocation(
    agent_playbook: AgentPlaybook, agent_session_id: UUID | None = None, *, pinned: bool = False
) -> AgentPlaybookInvocation:
    return AgentPlaybookInvocation(
        id=new_id(),
        created_at=utcnow(),
        agent_session_id=agent_session_id or new_id(),
        agent_playbook_id=agent_playbook.id,
        name=agent_playbook.name,
        version=agent_playbook.version,
        invoked_by=new_id(),
        pinned=pinned,
    )


def make_pin(
    agent_playbook: AgentPlaybook, kind: str = "assistant", agent_project_id: UUID | None = None
) -> AgentPlaybookPin:
    now, by = utcnow(), new_id()
    return AgentPlaybookPin(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        kind=kind,
        agent_project_id=agent_project_id,
        agent_playbook_id=agent_playbook.id,
        name=agent_playbook.name,
        version=agent_playbook.version,
    )


class AgentPlaybookStorageContract:
    async def test_versions_are_written_once_and_the_latest_reads_back(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org = new_id()
        first, second = make_agent_playbook(1), make_agent_playbook(2)
        assert await storage.create_agent_playbook(org, first, ())
        assert not await storage.create_agent_playbook(org, first, ())
        assert await storage.create_agent_playbook(org, second, ())
        with pytest.raises(UniqueKeyTaken):
            await storage.create_agent_playbook(org, make_agent_playbook(2), ())
        assert await storage.read_latest(org, first.name) == second
        assert await storage.read_agent_playbook(org, first.id) == first
        assert await storage.read_latest(org, "other") is None

    async def test_a_version_never_checked_reads_apart_from_one_checked_and_clean(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org = new_id()
        unchecked = make_agent_playbook(1).model_copy(update={"findings": None})
        clean = make_agent_playbook(2).model_copy(update={"findings": ()})
        for agent_playbook in (unchecked, clean):
            assert await storage.create_agent_playbook(org, agent_playbook, ())
        assert (await storage.read_agent_playbook(org, unchecked.id)) == unchecked
        assert (await storage.read_agent_playbook(org, clean.id)) == clean

    async def test_a_session_invokes_a_version_once(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org = new_id()
        agent_playbook = make_agent_playbook()
        await storage.create_agent_playbook(org, agent_playbook, ())
        first = make_invocation(agent_playbook)
        assert await storage.create_invocation(org, first) == first
        again = make_invocation(agent_playbook, first.agent_session_id)
        assert await storage.create_invocation(org, again) == first
        assert await storage.read_invocations(org, first.agent_session_id, 10) == [first]

    async def test_a_kind_manual_invocation_reads_back_pinned(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org = new_id()
        agent_playbook = make_agent_playbook()
        kind_manual = make_invocation(agent_playbook, pinned=True)
        assert await storage.create_invocation(org, kind_manual) == kind_manual
        assert await storage.read_invocations(org, kind_manual.agent_session_id, 10) == [
            kind_manual
        ]

    async def test_a_kind_holds_one_pin_for_the_tenant_and_one_an_agent_project_never_confused(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org, agent_project = new_id(), new_id()
        agent_playbook = make_agent_playbook()
        tenants, agent_projects = (
            make_pin(agent_playbook),
            make_pin(agent_playbook, agent_project_id=agent_project),
        )
        other = make_pin(agent_playbook, kind="analysis")
        for pin in (agent_projects, other, tenants):
            await storage.put_pin(org, pin, ())
        assert await storage.read_pin(org, "assistant", None) == tenants
        assert await storage.read_pin(org, "assistant", agent_project) == agent_projects
        assert await storage.read_pin(org, "assistant", new_id()) is None
        assert await storage.read_pins(org, 10) == [other, tenants, agent_projects]
        for taken in (
            make_pin(agent_playbook),
            make_pin(agent_playbook, agent_project_id=agent_project),
        ):
            with pytest.raises(UniqueKeyTaken):
                await storage.put_pin(org, taken, ())
        moved = tenants.model_copy(update={"version": 2, "agent_playbook_id": new_id()})
        await storage.put_pin(org, moved, ())
        assert await storage.read_pin(org, "assistant", None) == moved
        assert await storage.delete_pin(org, moved.id, ())
        assert not await storage.delete_pin(org, moved.id, ())
        assert await storage.read_pin(org, "assistant", None) is None
        assert await storage.read_pin(org, "assistant", agent_project) == agent_projects

    async def test_put_pin_of_another_tenants_id_is_refused_and_its_slot_is_its_own(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_playbook = make_agent_playbook()
        mine = make_pin(agent_playbook)
        await storage.put_pin(org_a, mine, ())
        with pytest.raises(TenantMismatch):
            await storage.put_pin(org_b, mine, ())
        theirs = make_pin(agent_playbook)
        await storage.put_pin(org_b, theirs, ())
        assert await storage.read_pin(org_a, "assistant", None) == mine
        assert await storage.read_pin(org_b, "assistant", None) == theirs

    async def test_read_pin_and_read_pins_of_another_tenant_find_nothing(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        await storage.put_pin(new_id(), make_pin(make_agent_playbook()), ())
        stranger = new_id()
        assert await storage.read_pin(stranger, "assistant", None) is None
        assert await storage.read_pins(stranger, 10) == []

    async def test_delete_pin_of_another_tenant_takes_nothing(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org = new_id()
        pin = make_pin(make_agent_playbook())
        await storage.put_pin(org, pin, ())
        assert not await storage.delete_pin(new_id(), pin.id, ())
        assert await storage.read_pin(org, "assistant", None) == pin

    async def test_create_agent_playbook_in_another_tenant_is_its_own(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_agent_playbook(org_a, make_agent_playbook(1), ())
        theirs = make_agent_playbook(1)
        assert await storage.create_agent_playbook(org_b, theirs, ())
        assert await storage.read_latest(org_b, theirs.name) == theirs

    async def test_read_agent_playbook_of_another_tenant_finds_nothing(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        agent_playbook = make_agent_playbook()
        await storage.create_agent_playbook(new_id(), agent_playbook, ())
        assert await storage.read_agent_playbook(new_id(), agent_playbook.id) is None

    async def test_read_latest_of_another_tenant_finds_nothing(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        agent_playbook = make_agent_playbook()
        await storage.create_agent_playbook(new_id(), agent_playbook, ())
        assert await storage.read_latest(new_id(), agent_playbook.name) is None

    async def test_create_invocation_in_another_tenant_is_its_own(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_playbook = make_agent_playbook()
        mine = make_invocation(agent_playbook)
        await storage.create_invocation(org_a, mine)
        theirs = make_invocation(agent_playbook, mine.agent_session_id)
        assert await storage.create_invocation(org_b, theirs) == theirs
        assert await storage.read_invocations(org_a, mine.agent_session_id, 10) == [mine]

    async def test_read_invocations_of_another_tenant_finds_nothing(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        invocation = make_invocation(make_agent_playbook())
        await storage.create_invocation(new_id(), invocation)
        assert await storage.read_invocations(new_id(), invocation.agent_session_id, 10) == []

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: AgentPlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        agent_playbook = make_agent_playbook()
        await storage.create_agent_playbook(org_a, agent_playbook, ())
        await storage.create_invocation(org_a, make_invocation(agent_playbook))
        await storage.put_pin(org_a, make_pin(agent_playbook), ())
        kept = make_agent_playbook()
        await storage.create_agent_playbook(org_b, kept, ())
        held = make_pin(kept)
        await storage.put_pin(org_b, held, ())
        assert await storage.purge_tenant(org_a, 10) == 3
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_latest(org_b, kept.name) == kept
        assert await storage.read_pins(org_b, 10) == [held]
