"""The intake storage contract: a tenant's account links and its sessions'
work bindings. The cases named in `CROSS_TENANT_CASES` are the tenant
fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes."""

from uuid import UUID

from acme.om.base import new_id, utcnow
from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.types.link import AccountLink, HandleKind, WorkBinding

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_link", "read_link", "create_binding", "read_binding", "purge_tenant"}
)
"""Every method of `IntakeStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""


def make_link(external_id: str = "U024BE7LH", user_id: UUID | None = None) -> AccountLink:
    return AccountLink(
        id=new_id(),
        created_at=utcnow(),
        integration="chat",
        external_id=external_id,
        user_id=user_id or new_id(),
        created_by=new_id(),
    )


def make_binding(handle: str = "acme/robot#12", session_id: UUID | None = None) -> WorkBinding:
    return WorkBinding(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id or new_id(),
        kind=HandleKind.PULL_REQUEST,
        handle=handle,
    )


class IntakeStorageContract:
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

    async def test_purge_tenant_takes_its_rows_and_no_other_tenants(
        self, storage: IntakeStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        await storage.create_link(org_a, make_link())
        await storage.create_binding(org_a, make_binding())
        kept = make_link()
        await storage.create_link(org_b, kept)
        assert await storage.purge_tenant(org_a, 10) == 2
        assert await storage.purge_tenant(org_a, 10) == 0
        assert await storage.read_link(org_b, "chat", kept.external_id) == kept
