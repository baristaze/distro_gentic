"""The account contract: one account per tenant, under the tenant's own id,
created once with the rows that announce it and changed by a
compare-and-set on its version. The cases named in `CROSS_TENANT_CASES`
are the tenant fence's evidence: each presents another tenant's account
and asserts that nothing is found and nothing changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.billing.storage import AccountStorageInterface
from acme.om.billing.types.account import Account, FundingMode, ZoneChange
from acme.om.exceptions import PreconditionFailed, TenantMismatch

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_account", "purge_tenant", "read_account", "write_account"}
)
"""Every method of `AccountStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_account(org_id: UUID, *, funding: FundingMode = FundingMode.PLATFORM) -> Account:
    now = utcnow()
    actor = new_id()
    return Account(
        id=org_id,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        funding=funding,
        key_ref="tenant-key-1" if funding is FundingMode.OWN_KEY else None,
        plan_id="team",
        plan_version=1,
        period_anchor=now,
        zones=(ZoneChange(zone="Europe/Istanbul", at=now),),
    )


class AccountStorageContract:
    @pytest.fixture
    def storage(self) -> AccountStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_an_account_is_created_once_and_read_back(
        self, storage: AccountStorageInterface
    ) -> None:
        org = new_id()
        account = make_account(org, funding=FundingMode.OWN_KEY)
        assert await storage.read_account(org) is None
        assert await storage.create_account(org, account, ())
        assert not await storage.create_account(org, make_account(org), ())
        assert await storage.read_account(org) == account

    async def test_a_change_lands_only_at_the_version_read(
        self, storage: AccountStorageInterface
    ) -> None:
        org = new_id()
        account = make_account(org)
        await storage.create_account(org, account, ())
        moved = account.model_copy(update={"credit_line_micros": 5_000, "version": 2})
        await storage.write_account(org, moved, 1, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_account(org, moved.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_account(org) == moved

    async def test_another_tenants_account_is_never_reached(
        self, storage: AccountStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        account = make_account(org)
        await storage.create_account(org, account, ())
        with pytest.raises(TenantMismatch):
            await storage.create_account(other, account, ())
        assert await storage.read_account(other) is None
        with pytest.raises(PreconditionFailed):
            await storage.write_account(other, account.model_copy(update={"version": 2}), 1, ())
        assert await storage.read_account(org) == account

    async def test_purge_tenant_deletes_the_tenants_account_and_no_other(
        self, storage: AccountStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        await storage.create_account(org, make_account(org), ())
        await storage.create_account(other, make_account(other), ())
        assert await storage.purge_tenant(org) == 1
        assert await storage.read_account(org) is None
        assert await storage.purge_tenant(org) == 0
        assert await storage.read_account(other) is not None
