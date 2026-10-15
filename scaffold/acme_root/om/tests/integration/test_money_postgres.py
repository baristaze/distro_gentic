"""The money over Postgres: the spend account and ledger contracts, what only the
database holds (no serving login rewrites or removes a ledger entry, and a
funding mode this process cannot read spends nothing), and a loop's call
held, settled, and charged in the one ledger, end to end."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import TextClause, text
from sqlalchemy.exc import DBAPIError

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agent_billing.impl.gate import MoneyGateImpl, MoneyGateOptions
from acme.om.agent_billing.impl.pager import OperatorPagerMemoryImpl
from acme.om.agent_billing.storage import SpendAccountStorageInterface, SpendLedgerStorageInterface
from acme.om.agent_billing.storage.impl.postgres import (
    SpendAccountStoragePostgresImpl,
    SpendLedgerStoragePostgresImpl,
)
from acme.om.agent_billing.types.spend_ledger import Charge, EntryKind, FundedHold
from acme.om.agent_billing.types.unit_plan import SPEND_UNITS, UNIT_PLANS
from acme.om.agents.types.run import RunEnd
from acme.om.base import EMPTY_UUID, new_id
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import SpenderUnknown
from acme.om.platform_root import build_platform_managers
from acme.om.spend_budgets.impl.pricing import LIST_PRICES
from acme.om.spend_budgets.storage.impl.postgres import SpendBudgetStoragePostgresImpl
from acme.om.spend_budgets.types.amount import Spend
from acme.om.spend_budgets.types.spend_budget import SpendBudgetScope, SpendBudgetScopeKind
from acme.om.spend_budgets.types.spend_hold import SpendHoldRequest
from acme.om.storage.impl.pg_base import LoginSessions, SessionFactory, set_scope
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.migrate import ensure_logins_everywhere
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

from contracts.doubles import context
from contracts.loops import reply, said
from contracts.money import money_over
from contracts.spend_account_storage import SpendAccountStorageContract, make_spend_account
from contracts.spend_ledger_storage import (
    SpendLedgerStorageContract,
    a_credit,
    a_funded_hold,
    closing,
)

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class TestAccountStoragePostgres(SpendAccountStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> SpendAccountStorageInterface:
        return SpendAccountStoragePostgresImpl(pg_sessions)


class TestSpendLedgerStoragePostgres(SpendLedgerStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> SpendLedgerStorageInterface:
        return SpendLedgerStoragePostgresImpl(pg_sessions)


async def refused(factory: SessionFactory, org_id: UUID, statement: TextClause) -> str:
    """The error a statement meets under the given scope, on a session of
    its own, since a refused statement ends its transaction."""
    async with factory() as session:
        await set_scope(session, org_id, None, None)
        with pytest.raises(DBAPIError) as error:
            await session.execute(statement)
        return str(error.value)


async def test_no_serving_login_rewrites_or_removes_a_ledger_entry(
    pg_sessions: LoginSessions, migration_settings: MigrationSettings
) -> None:
    """Every entry is written once: the serving logins may read and insert
    them and are refused an UPDATE and a DELETE by the database itself,
    after a deploy made the logins again. The counts beside them stay theirs
    to move."""
    settings = migration_settings
    await ensure_logins_everywhere(settings.master_databases(), settings.login_passwords())
    ledger = SpendLedgerStoragePostgresImpl(pg_sessions)
    org = new_id()
    await ledger.post_credit(org, a_credit(9_000))
    stored = await ledger.open_spend_hold(org, a_funded_hold(units=2))
    assert isinstance(stored, FundedHold)
    await ledger.close_spend_hold(org, *closing(stored, 2))

    for factory, scope in (
        (pg_sessions[DatabaseRole.ACTIVITY], org),
        (pg_sessions.system[DatabaseRole.ACTIVITY], EMPTY_UUID),
    ):
        for statement in (
            text("UPDATE activity.spend_ledger_entries SET created_at = created_at"),
            text("DELETE FROM activity.spend_ledger_entries"),
        ):
            error = await refused(factory, scope, statement)
            assert "permission denied for table spend_ledger_entries" in error, error
        async with factory() as db:
            await set_scope(db, scope, None, None)
            moved = text("UPDATE activity.spend_ledger_counts SET held = held RETURNING org_id")
            assert set((await db.execute(moved)).scalars().all()) == {org}
            await db.rollback()
    kinds = {type(e).__name__ for e in await ledger.read_entries(org, limit=10)}
    assert kinds == {"Credit", "FundedHold", "SpendSettlement", "Charge"}


async def test_a_funding_mode_this_process_cannot_read_spends_nothing(
    pg_sessions: LoginSessions,
) -> None:
    """A spend account whose funding mode is one this process does not know is no
    answer to who pays: the gate refuses before anything is held, and never
    reads it as the platform's key."""
    spend_accounts = SpendAccountStoragePostgresImpl(pg_sessions)
    ledger = SpendLedgerStoragePostgresImpl(pg_sessions)
    gate = MoneyGateImpl(
        SpendBudgetStoragePostgresImpl(pg_sessions),
        spend_accounts,
        ledger,
        OperatorPagerMemoryImpl(),
        UNIT_PLANS,
        SPEND_UNITS,
        MoneyGateOptions(),
    )
    ctx = context(Role.OWNER)
    assert await spend_accounts.create_spend_account(ctx.org_id, make_spend_account(ctx.org_id), ())
    async with pg_sessions[DatabaseRole.CORE]() as db:
        await set_scope(db, ctx.org_id, None, None)
        await db.execute(text("UPDATE core.spend_accounts SET funding = 'barter'"))
        await db.commit()
    request = SpendHoldRequest(
        spender_id=ctx.user_id,
        scopes=(SpendBudgetScope(kind=SpendBudgetScopeKind.TENANT, key=str(ctx.org_id)),),
        exposure=Spend(cost_micros=1_000, tokens=10),
        purpose="main",
    )

    with pytest.raises(SpenderUnknown):
        await gate.authorize(ctx, request)

    assert await ledger.read_entries(ctx.org_id, limit=10) == []


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_platform_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


async def test_a_loops_call_is_held_settled_and_charged_in_the_one_ledger_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    """End to end over Postgres: a prepaid tenant tops up through the
    provider's signed confirmation, a session's model call is held on the
    buckets, answered, settled, and charged at the price version its cap
    read, every entry in the one ledger."""
    owner = await an_owner(storage, tmp_path)
    money = money_over(tmp_path, storage=storage, owner=owner)
    await money.open(unit_plan="starter")
    await money.top_up(50_000)
    agent_session_id = await money.loop.start()
    await money.loop.say(agent_session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    ran = await money.loop.loops.run(owner, agent_session_id)

    assert ran.end is RunEnd.ENDED, ran
    (hold,) = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=10)
    assert isinstance(hold, FundedHold) and hold.agent_session_id == agent_session_id
    assert hold.priced is not None and hold.priced.version == LIST_PRICES.version
    found = await money.ledger.read_entries(owner.org_id, spend_hold_id=hold.id, limit=10)
    assert [type(entry).__name__ for entry in found] == ["Charge", "SpendSettlement", "FundedHold"]
    charge = found[0]
    assert isinstance(charge, Charge) and charge.price_version == LIST_PRICES.version
    assert charge.units > 0 and charge.draw.included == charge.units
    balances = await money.agent_billing.get_balances(owner)
    assert balances[0].spent == charge.units and balances[0].held == 0
    assert balances[2].added == 50_000
