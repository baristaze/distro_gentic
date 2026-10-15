"""The matrix's tenant storage contract: each tenant's pins and choices.
The cases named in `CROSS_TENANT_CASES` are the tenant fence's evidence:
each one presents another tenant's identifier and asserts that nothing is
found and nothing changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.language_models.types.fill import MAIN, SUMMARIZER, Fill
from acme.om.matrix.storage import MatrixTenantStorageInterface
from acme.om.matrix.types.tenant import FillOverride, MatrixPin

from contracts.matrix_storage import GPT, SONNET

INTERFACE = MatrixTenantStorageInterface
"""The storage interface whose cross-tenant cases this suite holds."""

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "write_pin",
        "read_pin",
        "write_override",
        "delete_override",
        "read_overrides",
        "purge_tenant",
    }
)
"""Every method of `MatrixTenantStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_pin(
    agent_session_id: UUID | None = None, fill_set_version: int = 1, matrix_version: int = 1
) -> MatrixPin:
    return MatrixPin(
        id=new_id(),
        created_at=utcnow(),
        agent_session_id=agent_session_id or new_id(),
        fill_set_version=fill_set_version,
        matrix_version=matrix_version,
    )


def make_choice(fill: Fill = SONNET, role: str = MAIN) -> FillOverride:
    now = utcnow()
    actor = new_id()
    return FillOverride(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        role=role,
        fill=fill,
    )


class MatrixTenantStorageContract:
    @pytest.fixture
    def storage(self) -> MatrixTenantStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_pin_is_written_once_a_fill_set_version(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        first = make_pin()
        assert await storage.write_pin(org, first) == first
        again = make_pin(first.agent_session_id, matrix_version=9)
        assert await storage.write_pin(org, again) == first
        later = make_pin(first.agent_session_id, fill_set_version=3, matrix_version=2)
        assert await storage.write_pin(org, later) == later
        assert await storage.read_pin(org, first.agent_session_id) == later
        assert await storage.read_pin(org, new_id()) is None

    async def test_write_pin_of_another_tenant_lands_nothing_here(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        pin = make_pin()
        await storage.write_pin(org_a, pin)
        with pytest.raises(PreconditionFailed):
            await storage.write_pin(org_b, pin)
        assert await storage.read_pin(org_b, pin.agent_session_id) is None
        assert await storage.read_pin(org_a, pin.agent_session_id) == pin

    async def test_read_pin_of_another_tenant_finds_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        pin = make_pin()
        await storage.write_pin(new_id(), pin)
        assert await storage.read_pin(new_id(), pin.agent_session_id) is None

    async def test_a_choice_replaces_the_last_for_its_role(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        first = make_choice()
        assert await storage.write_override(org, first) == first
        later = make_choice(GPT)
        stored = await storage.write_override(org, later)
        assert stored.id == first.id and stored.fill == GPT
        summary = make_choice(role=SUMMARIZER)
        await storage.write_override(org, summary)
        assert await storage.read_overrides(org, 10) == [stored, summary]
        assert await storage.read_overrides(org, 1) == [stored]
        assert await storage.delete_override(org, MAIN)
        assert not await storage.delete_override(org, MAIN)
        assert await storage.read_overrides(org, 10) == [summary]

    async def test_write_override_of_another_tenant_leaves_this_ones(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        mine = make_choice()
        await storage.write_override(org_a, mine)
        await storage.write_override(org_b, make_choice(GPT))
        assert await storage.read_overrides(org_a, 10) == [mine]

    async def test_delete_override_of_another_tenant_changes_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        org = new_id()
        mine = make_choice()
        await storage.write_override(org, mine)
        assert not await storage.delete_override(new_id(), MAIN)
        assert await storage.read_overrides(org, 10) == [mine]

    async def test_read_overrides_of_another_tenant_finds_nothing(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        await storage.write_override(new_id(), make_choice())
        assert await storage.read_overrides(new_id(), 10) == []

    async def test_purge_tenant_takes_the_tenants_rows_and_no_other(
        self, storage: MatrixTenantStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        await storage.write_pin(gone, make_pin())
        await storage.write_pin(gone, make_pin())
        await storage.write_override(gone, make_choice())
        stays = make_pin()
        await storage.write_pin(kept, stays)
        choice = make_choice()
        await storage.write_override(kept, choice)
        assert await storage.purge_tenant(gone, 2) == 2
        assert await storage.purge_tenant(gone, 2) == 1
        assert await storage.purge_tenant(gone, 2) == 0
        assert await storage.read_overrides(gone, 10) == []
        assert await storage.read_pin(kept, stays.agent_session_id) == stays
        assert await storage.read_overrides(kept, 10) == [choice]
