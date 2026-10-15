"""The platform's money behind the engine's gate: the gate a root hands the
engine's root as its budget gate, and the refusal of a root that did not.

    managers = build_platform_managers(storage, infra, ..., budget_gate=build_money_gate(storage))
    refuse_open_money(environment, managers)

Handed a money gate, the engine's root puts agent billing's call gate in front of
every model call: who pays is read first, the worst case is held on the
limits and drawn on the buckets in the one ledger, and the bill is read from
the price row the hold was read from. The maintenance worker's hold sweep
settles what nobody settled, through the same gate, on the same ledger."""

from collections.abc import Callable
from datetime import datetime

from acme.integrations.payments import PaymentProviderInterface
from acme.om.agent_billing.gate import MoneyGateInterface
from acme.om.agent_billing.impl.gate import MoneyGateImpl, MoneyGateOptions
from acme.om.agent_billing.impl.manager import AgentBillingManagerImpl
from acme.om.agent_billing.impl.pager import OperatorPagerLogImpl
from acme.om.agent_billing.impl.purge import AgentBillingPurgeImpl
from acme.om.agent_billing.manager import AgentBillingManagerInterface
from acme.om.agent_billing.pager import OperatorPagerInterface
from acme.om.agent_billing.purge import AgentBillingPurgeInterface
from acme.om.agent_billing.types.unit_plan import (
    SPEND_UNITS,
    UNIT_PLANS,
    SpendUnitScale,
    UnitPlanCatalog,
)
from acme.om.base import utcnow
from acme.om.exceptions import UnsafeConfiguration
from acme.om.platform_root import PlatformManagers
from acme.om.root import LOCAL
from acme.om.storage.root import StorageInterface


def build_money_gate(
    storage: StorageInterface,
    *,
    pager: OperatorPagerInterface | None = None,
    unit_plans: UnitPlanCatalog = UNIT_PLANS,
    spend_units: SpendUnitScale = SPEND_UNITS,
    options: MoneyGateOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> MoneyGateImpl:
    """Agent agent billing's gate over the budgets, the spend accounts, and the one ledger the
    storage holds. `pager` None pages the operator through the log the
    alerting reads; the unit plans and the unit scale are the ones the platform
    publishes."""
    return MoneyGateImpl(
        storage.get_budget_storage(),
        storage.get_spend_account_storage(),
        storage.get_spend_ledger_storage(),
        pager or OperatorPagerLogImpl(),
        unit_plans,
        spend_units,
        options or MoneyGateOptions(),
        clock,
    )


def build_agent_billing(
    storage: StorageInterface,
    managers: PlatformManagers,
    payments: PaymentProviderInterface,
    *,
    unit_plans: UnitPlanCatalog = UNIT_PLANS,
    spend_units: SpendUnitScale = SPEND_UNITS,
) -> AgentBillingManagerInterface:
    """Agent agent billing's manager over the spend accounts and the one ledger the money gate
    reads: a spend account opened here is the one the gate asks who pays of."""
    return AgentBillingManagerImpl(
        storage.get_spend_account_storage(),
        storage.get_spend_ledger_storage(),
        managers.budgets,
        managers.agent_sessions,
        managers.tenancy,
        payments,
        managers.outbox,
        unit_plans,
        spend_units,
    )


def build_agent_billing_purge(
    storage: StorageInterface, managers: PlatformManagers
) -> AgentBillingPurgeInterface:
    """Agent agent billing's part of a deleted tenant's purge, for the maintenance
    worker: the spend account goes, and the ledger stays."""
    return AgentBillingPurgeImpl(storage.get_spend_account_storage(), managers.tenancy)


def refuse_open_money(environment: str, managers: PlatformManagers) -> None:
    """Outside `local`, a root whose budget gate is not agent billing's is refused
    at boot: the engine's gate holds a call on its limits alone, and never
    asks who pays, so a tenant with no spend account would spend on the
    platform's key."""
    if environment == LOCAL:
        return
    gate = managers.budget_gate
    if not isinstance(gate, MoneyGateInterface):
        raise UnsafeConfiguration(
            f"{type(gate).__name__} is not the money gate, and is refused "
            f"when the environment is {environment}"
        )
