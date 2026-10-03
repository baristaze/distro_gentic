"""A loop with the platform's money behind its gate: the loop suites'
memory storage, scripted providers, and fake clock, with an account, the
one ledger, the price book, the payment provider's twin, and a pager that
keeps its pages. Nothing here reaches a network."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agents.impl.loop import LoopOptions
from acme.om.billing.impl.gate import MoneyCallGateImpl, MoneyGateImpl, MoneyGateOptions
from acme.om.billing.impl.manager import BillingManagerImpl
from acme.om.billing.impl.pager import OperatorPagerMemoryImpl
from acme.om.billing.impl.prices import PriceBookTableImpl
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.billing.types.plan import PLANS, UNITS, PlanCatalog
from acme.om.context import TenantContext
from acme.om.models.layer import ModelsLayer
from acme.om.root import Managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.windows.gate import CallGateInterface
from contracts.loops import Clock, Loop, loop_over


@dataclass
class Money:
    loop: Loop
    accounts: AccountStorageInterface
    ledger: MoneyLedgerStorageInterface
    gate: MoneyGateImpl
    calls: MoneyCallGateImpl
    billing: BillingManagerImpl
    prices: PriceBookTableImpl
    payments: PaymentProviderTwinImpl
    pager: OperatorPagerMemoryImpl

    async def open(
        self,
        *,
        plan: str = "starter",
        funding: FundingMode = FundingMode.PLATFORM,
        key_ref: str | None = None,
        zone: str = "UTC",
    ) -> None:
        request = AccountRequest(funding=funding, key_ref=key_ref, plan_id=plan, zone=zone)
        await self.billing.open_account(self.loop.owner, request)

    async def top_up(self, amount_micros: int) -> None:
        """A payment the provider confirms, posted as the provider's delivery."""
        payload, signature = self.payments.confirm(
            self.loop.owner.org_id, amount_micros, self.loop.clock()
        )
        await self.billing.confirm_payment(self.loop.owner, payload, signature)


def money_over(
    tmp_path: Path,
    *,
    prices: PriceBookTableImpl | None = None,
    options: MoneyGateOptions | None = None,
    plans: PlanCatalog = PLANS,
    loop_options: LoopOptions | None = None,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
    models_layer: ModelsLayer | None = None,
    tools_layer: Callable[[ToolsManagerInterface], ToolsManagerInterface] | None = None,
) -> Money:
    """`storage` None is the memory storage, and `owner` None a fresh
    tenant's owner; a suite over Postgres hands in both. The layers go to
    the loop's root as they are."""
    storage = storage or StorageMemoryImpl()
    accounts = storage.get_account_storage()
    ledger = storage.get_money_ledger_storage()
    pager = OperatorPagerMemoryImpl()
    book = prices or PriceBookTableImpl()
    built: list[tuple[MoneyGateImpl, MoneyCallGateImpl]] = []

    def gates(managers: Managers, clock: Clock) -> CallGateInterface:
        gate = MoneyGateImpl(
            storage.get_budget_storage(),
            accounts,
            ledger,
            pager,
            plans,
            UNITS,
            options or MoneyGateOptions(),
            clock,
        )
        calls = MoneyCallGateImpl(
            gate,
            book,
            managers.agent_sessions,
            version=None if models_layer is None else models_layer.version,
        )
        built.append((gate, calls))
        return calls

    loop = loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        options=loop_options,
        call_gate=gates,
        models_layer=models_layer,
        tools_layer=tools_layer,
    )
    ((gate, calls),) = built
    payments = PaymentProviderTwinImpl()
    billing = BillingManagerImpl(
        accounts,
        ledger,
        loop.managers.budgets,
        loop.managers.agent_sessions,
        payments,
        loop.managers.outbox,
        plans,
        UNITS,
        loop.clock,
    )
    return Money(loop, accounts, ledger, gate, calls, billing, book, payments, pager)
