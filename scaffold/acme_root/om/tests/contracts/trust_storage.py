"""The trust storage contract: a tenant's secrets by name, its provider keys
by reference, and its operators' content grants. The cases named in
`CROSS_TENANT_CASES` are the tenant fence's evidence: each one presents
another tenant's identifier and asserts that nothing is found and nothing
changes."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.integrations.model_providers.types import ProviderName
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.provider_key import KeyStatus, ProviderKey
from acme.om.trust.types.secret import SecretDeclaration, SecretOwnerKind, SecretStore

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_declaration",
        "read_declaration",
        "read_declarations",
        "create_key",
        "read_live_key",
        "read_keys",
        "touch_key",
        "write_grant",
        "read_grant",
        "delete_grant",
        "purge_declarations",
        "purge_keys",
        "purge_grants",
    }
)
"""Every method of `TrustStorageInterface` that takes a tenant has a case in
this module that presents another tenant's."""


def make_declaration(
    name: str = "deploy_token", store: SecretStore = SecretStore.CLOUD
) -> SecretDeclaration:
    now = utcnow()
    actor = new_id()
    return SecretDeclaration(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        name=name,
        variable="DEPLOY_TOKEN",
        owner_kind=SecretOwnerKind.PROJECT,
        owner_id=new_id(),
        scope="push:session-branch",
        store=store,
    )


def make_key(provider: ProviderName = ProviderName.ANTHROPIC) -> ProviderKey:
    now = utcnow()
    actor = new_id()
    return ProviderKey(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        provider=provider,
    )


def rotated(key: ProviderKey) -> ProviderKey:
    return key.model_copy(update={"status": KeyStatus.ROTATED, "version": key.version + 1})


def make_grant(identity_id: UUID | None = None, hours: int = 1) -> ContentGrant:
    now = utcnow()
    return ContentGrant(
        id=new_id(),
        created_at=now,
        identity_id=identity_id or new_id(),
        expires_at=now + timedelta(hours=hours),
    )


class TrustStorageContract:
    @pytest.fixture
    def storage(self) -> TrustStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    # Secret declarations.

    async def test_a_declaration_round_trips_by_name(self, storage: TrustStorageInterface) -> None:
        org = new_id()
        declaration = make_declaration()
        assert await storage.create_declaration(org, declaration, ())
        assert await storage.read_declaration(org, "deploy_token") == declaration
        assert await storage.read_declaration(org, "other") is None

    async def test_a_name_is_one_declaration_and_a_retry_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        first = make_declaration()
        assert await storage.create_declaration(org, first, ())
        assert not await storage.create_declaration(
            org, first.model_copy(update={"scope": "x"}), ()
        )
        with pytest.raises(UniqueKeyTaken):
            await storage.create_declaration(org, make_declaration(), ())
        assert await storage.read_declaration(org, first.name) == first

    async def test_declarations_list_by_name_after_a_name(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        for name in ("c_token", "a_token", "b_token"):
            assert await storage.create_declaration(org, make_declaration(name), ())
        listed = await storage.read_declarations(org, None, 10)
        assert [d.name for d in listed] == ["a_token", "b_token", "c_token"]
        after = await storage.read_declarations(org, "a_token", 1)
        assert [d.name for d in after] == ["b_token"]

    async def test_create_declaration_under_another_tenant_is_not_read_here(
        self, storage: TrustStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        declaration = make_declaration()
        assert await storage.create_declaration(org_a, declaration, ())
        assert not await storage.create_declaration(org_b, declaration, ())
        assert await storage.read_declaration(org_b, declaration.name) is None

    async def test_read_declaration_of_another_tenant_finds_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        assert await storage.create_declaration(new_id(), make_declaration(), ())
        assert await storage.read_declaration(new_id(), "deploy_token") is None

    async def test_read_declarations_of_another_tenant_finds_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        assert await storage.create_declaration(new_id(), make_declaration(), ())
        assert await storage.read_declarations(new_id(), None, 10) == []

    # Provider keys.

    async def test_a_rotation_writes_the_new_live_key_and_the_old_rotated(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        first, second = make_key(), make_key()
        await storage.create_key(org, first, None, ())
        assert await storage.read_live_key(org, ProviderName.ANTHROPIC) == first
        await storage.create_key(org, second, rotated(first), ())
        assert await storage.read_live_key(org, ProviderName.ANTHROPIC) == second
        statuses = {k.id: k.status for k in await storage.read_keys(org, 10)}
        assert statuses == {first.id: KeyStatus.ROTATED, second.id: KeyStatus.LIVE}

    async def test_one_live_key_a_provider_and_a_stale_rotation_lands_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        first = make_key()
        await storage.create_key(org, first, None, ())
        with pytest.raises(PreconditionFailed):
            await storage.create_key(org, make_key(), None, ())
        await storage.create_key(org, make_key(ProviderName.OPENAI), None, ())
        second = make_key()
        await storage.create_key(org, second, rotated(first), ())
        late = make_key()
        with pytest.raises(PreconditionFailed):
            await storage.create_key(org, late, rotated(first), ())
        assert await storage.read_live_key(org, ProviderName.ANTHROPIC) == second
        assert late.id not in {k.id for k in await storage.read_keys(org, 10)}

    async def test_keys_list_newest_first(self, storage: TrustStorageInterface) -> None:
        org = new_id()
        older = make_key(ProviderName.OPENAI)
        newer = make_key().model_copy(
            update={"created_at": older.created_at + timedelta(seconds=1)}
        )
        await storage.create_key(org, older, None, ())
        await storage.create_key(org, newer, None, ())
        assert [k.id for k in await storage.read_keys(org, 10)] == [newer.id, older.id]
        assert [k.id for k in await storage.read_keys(org, 1)] == [newer.id]

    async def test_a_use_is_marked_and_never_moved_back(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        key = make_key()
        await storage.create_key(org, key, None, ())
        at = utcnow()
        await storage.touch_key(org, key.id, at)
        await storage.touch_key(org, key.id, at - timedelta(minutes=1))
        live = await storage.read_live_key(org, ProviderName.ANTHROPIC)
        assert live is not None and live.last_used_at == at and live.version == key.version

    async def test_create_key_rotating_another_tenants_key_lands_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        first = make_key()
        await storage.create_key(org_a, first, None, ())
        with pytest.raises(PreconditionFailed):
            await storage.create_key(org_b, make_key(), rotated(first), ())
        assert await storage.read_live_key(org_a, ProviderName.ANTHROPIC) == first
        assert await storage.read_keys(org_b, 10) == []

    async def test_read_live_key_of_another_tenant_finds_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        await storage.create_key(new_id(), make_key(), None, ())
        assert await storage.read_live_key(new_id(), ProviderName.ANTHROPIC) is None

    async def test_read_keys_of_another_tenant_finds_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        await storage.create_key(new_id(), make_key(), None, ())
        assert await storage.read_keys(new_id(), 10) == []

    async def test_touch_key_of_another_tenant_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        key = make_key()
        await storage.create_key(org, key, None, ())
        await storage.touch_key(new_id(), key.id, utcnow())
        live = await storage.read_live_key(org, ProviderName.ANTHROPIC)
        assert live is not None and live.last_used_at is None

    # Content grants.

    async def test_a_grant_is_one_an_identity_and_a_new_one_replaces_it(
        self, storage: TrustStorageInterface
    ) -> None:
        org, operator = new_id(), new_id()
        first = make_grant(operator)
        assert await storage.write_grant(org, first) == first
        assert await storage.read_grant(org, operator) == first
        second = make_grant(operator, hours=2)
        await storage.write_grant(org, second)
        assert await storage.read_grant(org, operator) == second
        assert await storage.delete_grant(org, operator)
        assert not await storage.delete_grant(org, operator)
        assert await storage.read_grant(org, operator) is None

    async def test_write_grant_in_another_tenant_leaves_this_ones(
        self, storage: TrustStorageInterface
    ) -> None:
        org_a, org_b, operator = new_id(), new_id(), new_id()
        held = make_grant(operator)
        await storage.write_grant(org_a, held)
        await storage.write_grant(org_b, make_grant(operator, hours=3))
        assert await storage.read_grant(org_a, operator) == held

    async def test_read_grant_of_another_tenant_finds_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        operator = new_id()
        await storage.write_grant(new_id(), make_grant(operator))
        assert await storage.read_grant(new_id(), operator) is None

    async def test_delete_grant_of_another_tenant_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org, operator = new_id(), new_id()
        held = make_grant(operator)
        await storage.write_grant(org, held)
        assert not await storage.delete_grant(new_id(), operator)
        assert await storage.read_grant(org, operator) == held

    # The sweep.

    async def test_a_purge_takes_exactly_the_rows_named(
        self, storage: TrustStorageInterface
    ) -> None:
        gone, operator = new_id(), new_id()
        named, left = make_declaration("a_token"), make_declaration("b_token")
        key, other_key = make_key(), make_key(ProviderName.OPENAI)
        assert await storage.create_declaration(gone, named, ())
        assert await storage.create_declaration(gone, left, ())
        await storage.create_key(gone, key, None, ())
        await storage.create_key(gone, other_key, None, ())
        await storage.write_grant(gone, make_grant(operator))
        assert await storage.purge_declarations(gone, [named.id]) == 1
        assert await storage.purge_keys(gone, [key.id]) == 1
        assert await storage.purge_grants(gone, 10) == 1
        assert await storage.purge_declarations(gone, []) == 0
        assert [d.id for d in await storage.read_declarations(gone, None, 10)] == [left.id]
        assert [k.id for k in await storage.read_keys(gone, 10)] == [other_key.id]
        assert await storage.read_grant(gone, operator) is None

    async def test_purge_declarations_of_another_tenant_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        stays = make_declaration()
        assert await storage.create_declaration(org, stays, ())
        assert await storage.purge_declarations(new_id(), [stays.id]) == 0
        assert await storage.read_declaration(org, stays.name) == stays

    async def test_purge_keys_of_another_tenant_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org = new_id()
        stays = make_key()
        await storage.create_key(org, stays, None, ())
        assert await storage.purge_keys(new_id(), [stays.id]) == 0
        assert await storage.read_live_key(org, ProviderName.ANTHROPIC) == stays

    async def test_purge_grants_of_another_tenant_changes_nothing(
        self, storage: TrustStorageInterface
    ) -> None:
        org, operator = new_id(), new_id()
        stays = make_grant(operator)
        await storage.write_grant(org, stays)
        assert await storage.purge_grants(new_id(), 10) == 0
        assert await storage.read_grant(org, operator) == stays
