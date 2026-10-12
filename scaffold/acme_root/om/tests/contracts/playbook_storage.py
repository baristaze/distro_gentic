"""The playbooks storage contract: every published version, written once
with the findings read in it, none on one never checked, the playbooks
each session invoked, and the versions pinned to kinds, one a kind in a
project and one for the tenant, never confused. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import TenantMismatch, UniqueKeyTaken
from acme.om.levers.types.lever import LeverCheck, LeverFinding
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import (
    Playbook,
    PlaybookGate,
    PlaybookInvocation,
    PlaybookPin,
)
from acme.om.tools.types.policy import Decision

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_playbook",
        "read_playbook",
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
        findings=(
            LeverFinding(
                check=LeverCheck.UNBOUNDED_RETRY,
                detail="“keep trying” with no stopping condition",
                excerpt="Keep trying the build until it is green.",
            ),
        ),
    )


def make_invocation(
    playbook: Playbook, session_id: UUID | None = None, *, pinned: bool = False
) -> PlaybookInvocation:
    return PlaybookInvocation(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id or new_id(),
        playbook_id=playbook.id,
        name=playbook.name,
        version=playbook.version,
        invoked_by=new_id(),
        pinned=pinned,
    )


def make_pin(
    playbook: Playbook, kind: str = "assistant", project_id: UUID | None = None
) -> PlaybookPin:
    now, by = utcnow(), new_id()
    return PlaybookPin(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        kind=kind,
        project_id=project_id,
        playbook_id=playbook.id,
        name=playbook.name,
        version=playbook.version,
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

    async def test_a_version_never_checked_reads_apart_from_one_checked_and_clean(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org = new_id()
        unchecked = make_playbook(1).model_copy(update={"findings": None})
        clean = make_playbook(2).model_copy(update={"findings": ()})
        for playbook in (unchecked, clean):
            assert await storage.create_playbook(org, playbook, ())
        assert (await storage.read_playbook(org, unchecked.id)) == unchecked
        assert (await storage.read_playbook(org, clean.id)) == clean

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

    async def test_a_manual_invocation_reads_back_pinned(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org = new_id()
        playbook = make_playbook()
        manual = make_invocation(playbook, pinned=True)
        assert await storage.create_invocation(org, manual) == manual
        assert await storage.read_invocations(org, manual.session_id, 10) == [manual]

    async def test_a_kind_holds_one_pin_for_the_tenant_and_one_a_project_never_confused(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org, project = new_id(), new_id()
        playbook = make_playbook()
        tenants, projects = make_pin(playbook), make_pin(playbook, project_id=project)
        other = make_pin(playbook, kind="analysis")
        for pin in (projects, other, tenants):
            await storage.put_pin(org, pin, ())
        assert await storage.read_pin(org, "assistant", None) == tenants
        assert await storage.read_pin(org, "assistant", project) == projects
        assert await storage.read_pin(org, "assistant", new_id()) is None
        assert await storage.read_pins(org, 10) == [other, tenants, projects]
        for taken in (make_pin(playbook), make_pin(playbook, project_id=project)):
            with pytest.raises(UniqueKeyTaken):
                await storage.put_pin(org, taken, ())
        moved = tenants.model_copy(update={"version": 2, "playbook_id": new_id()})
        await storage.put_pin(org, moved, ())
        assert await storage.read_pin(org, "assistant", None) == moved
        assert await storage.delete_pin(org, moved.id, ())
        assert not await storage.delete_pin(org, moved.id, ())
        assert await storage.read_pin(org, "assistant", None) is None
        assert await storage.read_pin(org, "assistant", project) == projects

    async def test_put_pin_of_another_tenants_id_is_refused_and_its_slot_is_its_own(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        playbook = make_playbook()
        mine = make_pin(playbook)
        await storage.put_pin(org_a, mine, ())
        with pytest.raises(TenantMismatch):
            await storage.put_pin(org_b, mine, ())
        theirs = make_pin(playbook)
        await storage.put_pin(org_b, theirs, ())
        assert await storage.read_pin(org_a, "assistant", None) == mine
        assert await storage.read_pin(org_b, "assistant", None) == theirs

    async def test_read_pin_and_read_pins_of_another_tenant_find_nothing(
        self, storage: PlaybookStorageInterface
    ) -> None:
        await storage.put_pin(new_id(), make_pin(make_playbook()), ())
        stranger = new_id()
        assert await storage.read_pin(stranger, "assistant", None) is None
        assert await storage.read_pins(stranger, 10) == []

    async def test_delete_pin_of_another_tenant_takes_nothing(
        self, storage: PlaybookStorageInterface
    ) -> None:
        org = new_id()
        pin = make_pin(make_playbook())
        await storage.put_pin(org, pin, ())
        assert not await storage.delete_pin(new_id(), pin.id, ())
        assert await storage.read_pin(org, "assistant", None) == pin

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
        await storage.put_pin(org_a, make_pin(playbook), ())
        kept = make_playbook()
        await storage.create_playbook(org_b, kept, ())
        held = make_pin(kept)
        await storage.put_pin(org_b, held, ())
        assert await storage.purge_tenant(org_a, 10) == 3
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_latest(org_b, kept.name) == kept
        assert await storage.read_pins(org_b, 10) == [held]
