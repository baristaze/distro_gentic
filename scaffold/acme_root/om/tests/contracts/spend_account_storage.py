"""The spend account contract: one spend account per tenant, under the tenant's own id,
created once with the rows that announce it and changed by a
compare-and-set on its version. The cases named in `CROSS_TENANT_CASES`
are the tenant fence's evidence: each presents another tenant's spend account
and asserts that nothing is found and nothing changes."""

from uuid import UUID

import pytest

from acme.om.agent_billing.storage import SpendAccountStorageInterface
from acme.om.agent_billing.types.spend_account import FundingMode, SpendAccount, ZoneChange
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, TenantMismatch

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_spend_account", "purge_tenant", "read_spend_account", "write_spend_account"}
)
"""Every method of `SpendAccountStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_spend_account(
    org_id: UUID, *, funding: FundingMode = FundingMode.PLATFORM
) -> SpendAccount:
    now = utcnow()
    actor = new_id()
    return SpendAccount(
        id=org_id,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        funding=funding,
        key_ref="tenant-key-1" if funding is FundingMode.OWN_KEY else None,
        unit_plan_id="team",
        unit_plan_version=1,
        period_anchor=now,
        zones=(ZoneChange(zone="Europe/Istanbul", at=now),),
    )


class SpendAccountStorageContract:
    @pytest.fixture
    def storage(self) -> SpendAccountStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_an_account_is_created_once_and_read_back(
        self, storage: SpendAccountStorageInterface
    ) -> None:
        org = new_id()
        spend_account = make_spend_account(org, funding=FundingMode.OWN_KEY)
        assert await storage.read_spend_account(org) is None
        assert await storage.create_spend_account(org, spend_account, ())
        assert not await storage.create_spend_account(org, make_spend_account(org), ())
        assert await storage.read_spend_account(org) == spend_account

    async def test_a_change_lands_only_at_the_version_read(
        self, storage: SpendAccountStorageInterface
    ) -> None:
        org = new_id()
        spend_account = make_spend_account(org)
        await storage.create_spend_account(org, spend_account, ())
        moved = spend_account.model_copy(update={"credit_line_micros": 5_000, "version": 2})
        await storage.write_spend_account(org, moved, 1, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_spend_account(org, moved.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_spend_account(org) == moved

    async def test_another_tenants_account_is_never_reached(
        self, storage: SpendAccountStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        spend_account = make_spend_account(org)
        await storage.create_spend_account(org, spend_account, ())
        with pytest.raises(TenantMismatch):
            await storage.create_spend_account(other, spend_account, ())
        assert await storage.read_spend_account(other) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_spend_account(
                other, spend_account.model_copy(update={"version": 2}), 1, ()
            )
        assert await storage.read_spend_account(org) == spend_account

    async def test_purge_tenant_deletes_the_tenants_account_and_no_other(
        self, storage: SpendAccountStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        await storage.create_spend_account(org, make_spend_account(org), ())
        await storage.create_spend_account(other, make_spend_account(other), ())
        assert await storage.purge_tenant(org) == 1
        assert await storage.read_spend_account(org) is None
        assert await storage.purge_tenant(org) == 0
        assert await storage.read_spend_account(other) is not None
