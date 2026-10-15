"""A loop with the platform's money behind its gate: the loop suites'
memory storage, scripted providers, and fake clock, with a spend account, the
one ledger, the price book, the payment provider's twin, and a pager that
keeps its pages. Nothing here reaches a network."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agent_billing.impl.gate import MoneyCallGateImpl, MoneyGateImpl, MoneyGateOptions
from acme.om.agent_billing.impl.manager import AgentBillingManagerImpl
from acme.om.agent_billing.impl.pager import OperatorPagerMemoryImpl
from acme.om.agent_billing.impl.prices import PriceBookTableImpl
from acme.om.agent_billing.prices import PriceBookInterface
from acme.om.agent_billing.storage import SpendAccountStorageInterface, SpendLedgerStorageInterface
from acme.om.agent_billing.types.spend_account import FundingMode, SpendAccountRequest
from acme.om.agent_billing.types.unit_plan import SPEND_UNITS, UNIT_PLANS, UnitPlanCatalog
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agents.impl.loop import LoopOptions
from acme.om.agents.types.kind import AgentKind
from acme.om.context import Role, TenantContext
from acme.om.language_models.layer import LanguageModelsLayer
from acme.om.platform_root import PlatformManagers, PlatformRootOptions
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.types.org import Org
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface
from acme.om.windows.gate import CallGateInterface

from contracts.doubles import context
from contracts.factories import make_org
from contracts.loops import ASSISTANT, DELIVERY, Clock
from contracts.platform_loops import PlatformLoop, platform_loop_over


@dataclass
class Money:
    loop: PlatformLoop
    spend_accounts: SpendAccountStorageInterface
    ledger: SpendLedgerStorageInterface
    gate: MoneyGateImpl
    calls: MoneyCallGateImpl
    agent_billing: AgentBillingManagerImpl
    prices: PriceBookInterface
    payments: PaymentProviderTwinImpl
    pager: OperatorPagerMemoryImpl
    tenant: Org | None = None

    async def open(
        self,
        *,
        unit_plan: str = "starter",
        funding: FundingMode = FundingMode.PLATFORM,
        key_ref: str | None = None,
        zone: str = "UTC",
    ) -> None:
        if self.tenant is not None:
            # A fresh tenant's org, where tenancy reads it: agent billing wakes the
            # tenant's sessions under the tenant's own service context.
            await self.loop.storage.get_tenancy_storage().write_org(self.tenant.id, self.tenant)
        request = SpendAccountRequest(
            funding=funding, key_ref=key_ref, unit_plan_id=unit_plan, zone=zone
        )
        await self.agent_billing.open_spend_account(self.loop.owner, request)

    async def top_up(self, amount_micros: int) -> None:
        """A payment the provider confirms, posted as the provider's delivery."""
        payload, signature = self.payments.confirm(
            self.loop.owner.org_id, amount_micros, self.loop.clock()
        )
        await self.agent_billing.confirm_payment(self.loop.owner, payload, signature)


def money_over(
    tmp_path: Path,
    *,
    prices: PriceBookInterface | None = None,
    options: MoneyGateOptions | None = None,
    unit_plans: UnitPlanCatalog = UNIT_PLANS,
    loop_options: LoopOptions | None = None,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
    language_models_layer: LanguageModelsLayer | None = None,
    tools_layer: Callable[[ToolsManagerInterface], ToolsManagerInterface] | None = None,
    kinds: tuple[AgentKind, ...] = (ASSISTANT, DELIVERY),
    extra: tuple[ToolInterface, ...] = (),
) -> Money:
    """`storage` None is the memory storage, and `owner` None a fresh
    tenant's owner; a suite over Postgres hands in both. The layers go to
    the loop's root as they are, and `kinds` and `extra` to the loop."""
    storage = storage or StorageMemoryImpl()
    spend_accounts = storage.get_spend_account_storage()
    ledger = storage.get_spend_ledger_storage()
    pager = OperatorPagerMemoryImpl()
    book = prices or PriceBookTableImpl()
    built: list[tuple[MoneyGateImpl, MoneyCallGateImpl]] = []
    tenant = None
    if owner is None:
        tenant = make_org()
        owner = context(Role.OWNER, tenant)

    def gates(managers: PlatformManagers, clock: Clock) -> CallGateInterface:
        gate = MoneyGateImpl(
            storage.get_spend_budget_storage(),
            spend_accounts,
            ledger,
            pager,
            unit_plans,
            SPEND_UNITS,
            options or MoneyGateOptions(),
            clock,
        )
        calls = MoneyCallGateImpl(
            gate,
            book,
            managers.agent_sessions,
            managers.budgets,
            SessionAgentProjectsBoundImpl(storage.get_agent_project_storage()),
            version=None if language_models_layer is None else language_models_layer.version,
            tier=None if language_models_layer is None else language_models_layer.tier,
            clock=clock,
        )
        built.append((gate, calls))
        return calls

    loop = platform_loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        options=loop_options,
        call_gate=gates,
        language_models_layer=language_models_layer,
        kinds=kinds,
        extra=extra,
        platform=PlatformRootOptions(tools_layer=tools_layer),
    )
    ((gate, calls),) = built
    payments = PaymentProviderTwinImpl()
    agent_billing = AgentBillingManagerImpl(
        spend_accounts,
        ledger,
        loop.managers.budgets,
        loop.managers.agent_sessions,
        loop.managers.tenancy,
        payments,
        loop.managers.outbox,
        unit_plans,
        SPEND_UNITS,
        loop.clock,
    )
    return Money(
        loop, spend_accounts, ledger, gate, calls, agent_billing, book, payments, pager, tenant
    )
