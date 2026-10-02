"""The money over Postgres: the account and ledger contracts, what only the
database holds (no serving login rewrites or removes a ledger entry, and a
funding mode this process cannot read spends nothing), and a loop's call
held, settled, and charged in the one ledger, end to end."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from contracts.account_storage import AccountStorageContract, make_account
from contracts.doubles import context
from contracts.loops import reply, said
from contracts.money import money_over
from contracts.money_ledger_storage import (
    MoneyLedgerStorageContract,
    a_credit,
    a_funded_hold,
    closing,
)
from sqlalchemy import TextClause, text
from sqlalchemy.exc import DBAPIError

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agents.types.run import RunEnd
from acme.om.base import EMPTY_UUID, new_id
from acme.om.billing.impl.gate import MoneyGateImpl, MoneyGateOptions
from acme.om.billing.impl.pager import OperatorPagerMemoryImpl
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.billing.storage.impl.postgres import (
    AccountStoragePostgresImpl,
    MoneyLedgerStoragePostgresImpl,
)
from acme.om.billing.types.ledger import Charge, EntryKind, FundedHold
from acme.om.billing.types.plan import PLANS, UNITS
from acme.om.budgets.impl.pricing import LIST_PRICES
from acme.om.budgets.storage.impl.postgres import BudgetStoragePostgresImpl
from acme.om.budgets.types.amount import Spend
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind
from acme.om.budgets.types.hold import HoldRequest
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.exceptions import SpenderUnknown
from acme.om.root import build_managers
from acme.om.storage.impl.pg_base import LoginSessions, SessionFactory, set_scope
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.migrate import ensure_logins_at
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")


class TestAccountStoragePostgres(AccountStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> AccountStorageInterface:
        return AccountStoragePostgresImpl(pg_sessions)


class TestMoneyLedgerStoragePostgres(MoneyLedgerStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> MoneyLedgerStorageInterface:
        return MoneyLedgerStoragePostgresImpl(pg_sessions)


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
    await ensure_logins_at(settings.master_url(), settings.login_passwords())
    ledger = MoneyLedgerStoragePostgresImpl(pg_sessions)
    org = new_id()
    await ledger.post_credit(org, a_credit(9_000))
    stored = await ledger.open_hold(org, a_funded_hold(units=2))
    assert isinstance(stored, FundedHold)
    await ledger.close_hold(org, *closing(stored, 2))

    for factory, scope in (
        (pg_sessions[DatabaseRole.ACTIVITY], org),
        (pg_sessions.system[DatabaseRole.ACTIVITY], EMPTY_UUID),
    ):
        for statement in (
            text("UPDATE activity.ledger_entries SET created_at = created_at"),
            text("DELETE FROM activity.ledger_entries"),
        ):
            error = await refused(factory, scope, statement)
            assert "permission denied for table ledger_entries" in error, error
        async with factory() as db:
            await set_scope(db, scope, None, None)
            moved = text("UPDATE activity.ledger_counts SET held = held RETURNING org_id")
            assert set((await db.execute(moved)).scalars().all()) == {org}
            await db.rollback()
    kinds = {type(e).__name__ for e in await ledger.read_entries(org, limit=10)}
    assert kinds == {"Credit", "FundedHold", "Settlement", "Charge"}


async def test_a_funding_mode_this_process_cannot_read_spends_nothing(
    pg_sessions: LoginSessions,
) -> None:
    """An account whose funding mode is one this process does not know is no
    answer to who pays: the gate refuses before anything is held, and never
    reads it as the platform's key."""
    accounts = AccountStoragePostgresImpl(pg_sessions)
    ledger = MoneyLedgerStoragePostgresImpl(pg_sessions)
    gate = MoneyGateImpl(
        BudgetStoragePostgresImpl(pg_sessions),
        accounts,
        ledger,
        OperatorPagerMemoryImpl(),
        PLANS,
        UNITS,
        MoneyGateOptions(),
    )
    ctx = context(Role.OWNER)
    assert await accounts.create_account(ctx.org_id, make_account(ctx.org_id), ())
    async with pg_sessions[DatabaseRole.CORE]() as db:
        await set_scope(db, ctx.org_id, None, None)
        await db.execute(text("UPDATE core.billing_accounts SET funding = 'barter'"))
        await db.commit()
    request = HoldRequest(
        spender_id=ctx.user_id,
        scopes=(BudgetScope(kind=BudgetScopeKind.TENANT, key=str(ctx.org_id)),),
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
    managers = build_managers(storage, InfraConfiguredImpl(settings))
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
    await money.open(plan="starter")
    await money.top_up(50_000)
    session_id = await money.loop.start()
    await money.loop.say(session_id, "What is the total?")
    money.loop.anthropic.add(reply(said("The total is 12.")))

    ran = await money.loop.loops.run(owner, session_id)

    assert ran.end is RunEnd.ENDED, ran
    (hold,) = await money.ledger.read_entries(owner.org_id, kind=EntryKind.HOLD, limit=10)
    assert isinstance(hold, FundedHold) and hold.session_id == session_id
    assert hold.priced is not None and hold.priced.version == LIST_PRICES.version
    found = await money.ledger.read_entries(owner.org_id, hold_id=hold.id, limit=10)
    assert [type(entry).__name__ for entry in found] == ["Charge", "Settlement", "FundedHold"]
    charge = found[0]
    assert isinstance(charge, Charge) and charge.price_version == LIST_PRICES.version
    assert charge.units > 0 and charge.draw.included == charge.units
    balances = await money.billing.get_balances(owner)
    assert balances[0].spent == charge.units and balances[0].held == 0
    assert balances[2].added == 50_000
