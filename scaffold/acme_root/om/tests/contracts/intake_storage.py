"""The intake storage contract: the installations a tenant connected, its
account links, and its sessions' work bindings. The cases named in `CROSS_TENANT_CASES` are the tenant
fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes."""

from datetime import timedelta
from uuid import UUID

from acme.om.base import new_id, utcnow
from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.types.link import (
    AccountLink,
    HandleKind,
    Installation,
    PlatformAct,
    WorkBinding,
)

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_installation",
        "create_link",
        "read_link",
        "read_user_links",
        "delete_link",
        "create_binding",
        "read_binding",
        "read_session_bindings",
        "record_act",
        "read_act",
        "purge_tenant",
    }
)
"""Every method of `IntakeStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""


def make_installation(installation: str = "71001") -> Installation:
    return Installation(
        id=new_id(),
        created_at=utcnow(),
        integration="forge",
        installation=installation,
        created_by=new_id(),
    )


def make_link(external_id: str = "U024BE7LH", user_id: UUID | None = None) -> AccountLink:
    return AccountLink(
        id=new_id(),
        created_at=utcnow(),
        integration="chat",
        external_id=external_id,
        user_id=user_id or new_id(),
        created_by=new_id(),
    )


def make_binding(handle: str = "acme/checkout#12", session_id: UUID | None = None) -> WorkBinding:
    return WorkBinding(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id or new_id(),
        kind=HandleKind.PULL_REQUEST,
        handle=handle,
    )


def make_act(ref: str = "sha-4f2a", session_id: UUID | None = None) -> PlatformAct:
    return PlatformAct(
        id=new_id(),
        created_at=utcnow(),
        integration="forge",
        ref=ref,
        session_id=session_id or new_id(),
    )


class IntakeStorageContract:
    async def test_the_latest_act_under_a_name_holds(self, storage: IntakeStorageInterface) -> None:
        org = new_id()
        first = make_act()
        await storage.record_act(org, first)
        later = make_act().model_copy(
            update={"created_at": first.created_at + timedelta(seconds=1)}
        )
        await storage.record_act(org, later)
        assert await storage.read_act(org, "forge", ["sha-4f2a"]) == later
        other = make_act("comment-9").model_copy(
            update={"created_at": later.created_at + timedelta(seconds=1)}
        )
        await storage.record_act(org, other)
        assert await storage.read_act(org, "forge", ["sha-4f2a", "comment-9"]) == other
        assert await storage.read_act(org, "chat", ["sha-4f2a"]) is None
        assert await storage.read_act(org, "forge", []) is None

    async def test_record_act_in_another_tenant_is_its_own(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_act()
        await storage.record_act(org_a, mine)
        await storage.record_act(org_b, make_act())
        assert await storage.read_act(org_a, "forge", [mine.ref]) == mine

    async def test_read_act_of_another_tenant_finds_nothing(
        self, storage: IntakeStorageInterface
    ) -> None:
        act = make_act()
        await storage.record_act(new_id(), act)
        assert await storage.read_act(new_id(), "forge", [act.ref]) is None

    async def test_an_account_is_one_link_and_the_first_answers(
        self, storage: IntakeStorageInterface
    ) -> None:
        org = new_id()
        first = make_link()
        assert await storage.create_link(org, first) == first
        assert await storage.create_link(org, make_link()) == first
        assert await storage.read_link(org, "chat", first.external_id) == first
        assert await storage.read_link(org, "forge", first.external_id) is None

    async def test_a_handle_is_one_binding_and_the_first_answers(
        self, storage: IntakeStorageInterface
    ) -> None:
        org = new_id()
        first = make_binding()
        assert await storage.create_binding(org, first) == first
        assert await storage.create_binding(org, make_binding()) == first
        found = await storage.read_binding(org, HandleKind.PULL_REQUEST, first.handle)
        assert found == first
        assert await storage.read_binding(org, HandleKind.BRANCH, first.handle) is None

    async def test_a_sessions_bindings_are_its_own_oldest_first(
        self, storage: IntakeStorageInterface
    ) -> None:
        org, session_id = new_id(), new_id()
        branch = make_binding("routes-for-sessions", session_id).model_copy(
            update={"kind": HandleKind.BRANCH}
        )
        pull = make_binding("acme/checkout#12", session_id).model_copy(
            update={"created_at": branch.created_at + timedelta(seconds=1)}
        )
        await storage.create_binding(org, pull)
        await storage.create_binding(org, branch)
        await storage.create_binding(org, make_binding("acme/checkout#13"))
        assert await storage.read_session_bindings(org, session_id, 10) == [branch, pull]
        assert await storage.read_session_bindings(org, session_id, 1) == [branch]
        assert await storage.read_session_bindings(org, new_id(), 10) == []

    async def test_create_link_in_another_tenant_is_its_own(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_link()
        await storage.create_link(org_a, mine)
        theirs = make_link()
        assert await storage.create_link(org_b, theirs) == theirs
        assert await storage.read_link(org_a, "chat", mine.external_id) == mine

    async def test_read_link_of_another_tenant_finds_nothing(
        self, storage: IntakeStorageInterface
    ) -> None:
        link = make_link()
        await storage.create_link(new_id(), link)
        assert await storage.read_link(new_id(), "chat", link.external_id) is None

    async def test_a_users_links_are_read_and_one_unlinked_in_its_tenant_alone(
        self, storage: IntakeStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        user = new_id()
        chat = await storage.create_link(org, make_link("U-ANN", user))
        forge = await storage.create_link(
            org, make_link("ann", user).model_copy(update={"integration": "forge"})
        )
        await storage.create_link(org, make_link("U-BOB"))
        assert await storage.read_user_links(org, user, 10) == [chat, forge]
        assert await storage.read_user_links(other, user, 10) == []
        assert not await storage.delete_link(other, "chat", "U-ANN")
        assert await storage.read_link(org, "chat", "U-ANN") == chat
        assert await storage.delete_link(org, "chat", "U-ANN")
        assert not await storage.delete_link(org, "chat", "U-ANN")
        assert await storage.read_user_links(org, user, 10) == [forge]

    async def test_create_binding_in_another_tenant_is_its_own(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_binding()
        await storage.create_binding(org_a, mine)
        theirs = make_binding()
        assert await storage.create_binding(org_b, theirs) == theirs
        found = await storage.read_binding(org_a, HandleKind.PULL_REQUEST, mine.handle)
        assert found == mine

    async def test_read_binding_of_another_tenant_finds_nothing(
        self, storage: IntakeStorageInterface
    ) -> None:
        binding = make_binding()
        await storage.create_binding(new_id(), binding)
        assert await storage.read_binding(new_id(), HandleKind.PULL_REQUEST, binding.handle) is None

    async def test_read_session_bindings_of_another_tenant_finds_nothing(
        self, storage: IntakeStorageInterface
    ) -> None:
        binding = make_binding()
        await storage.create_binding(new_id(), binding)
        assert await storage.read_session_bindings(new_id(), binding.session_id, 10) == []

    async def test_create_installation_another_tenant_holds_connects_nothing(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_installation()
        assert await storage.create_installation(org_a, mine) == mine
        assert await storage.create_installation(org_b, make_installation()) is None
        assert await storage.create_installation(org_a, make_installation()) == mine
        assert await storage.read_installation_org("forge", mine.installation) == org_a

    async def test_read_installation_org_reads_every_tenants_and_names_one(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_installation(org_a, make_installation("71001"))
        await storage.create_installation(org_b, make_installation("72002"))
        assert await storage.read_installation_org("forge", "71001") == org_a
        assert await storage.read_installation_org("forge", "72002") == org_b
        assert await storage.read_installation_org("chat", "71001") is None
        assert await storage.read_installation_org("forge", "79999") is None

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_installation(org_a, make_installation())
        await storage.create_link(org_a, make_link())
        await storage.create_binding(org_a, make_binding())
        await storage.record_act(org_a, make_act())
        kept = make_link()
        await storage.create_link(org_b, kept)
        assert await storage.purge_tenant(org_a, 10) == 4
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_installation_org("forge", "71001") is None
        assert await storage.read_link(org_b, "chat", kept.external_id) == kept
