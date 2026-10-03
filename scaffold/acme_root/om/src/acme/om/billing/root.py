"""The platform's money behind the engine's gate: the gate a root hands the
engine's root as its budget gate, and the refusal of a root that did not.

    managers = build_managers(storage, infra, ..., budget_gate=build_money_gate(storage))
    refuse_open_money(environment, managers)

Handed a money gate, the engine's root puts billing's call gate in front of
every model call: who pays is read first, the worst case is held on the
limits and drawn on the buckets in the one ledger, and the bill is read from
the price row the hold was read from. The maintenance worker's hold sweep
settles what nobody settled, through the same gate, on the same ledger."""

from collections.abc import Callable
from datetime import datetime

from acme.om.base import utcnow
from acme.om.billing.gate import MoneyGateInterface
from acme.om.billing.impl.gate import MoneyGateImpl, MoneyGateOptions
from acme.om.billing.impl.pager import OperatorPagerLogImpl
from acme.om.billing.pager import OperatorPagerInterface
from acme.om.billing.types.plan import PLANS, UNITS, PlanCatalog, UnitScale
from acme.om.exceptions import UnsafeConfiguration
from acme.om.root import LOCAL, Managers
from acme.om.storage.root import StorageInterface


def build_money_gate(
    storage: StorageInterface,
    *,
    pager: OperatorPagerInterface | None = None,
    plans: PlanCatalog = PLANS,
    units: UnitScale = UNITS,
    options: MoneyGateOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> MoneyGateImpl:
    """Billing's gate over the budgets, the accounts, and the one ledger the
    storage holds. `pager` None pages the operator through the log the
    alerting reads; the plans and the unit scale are the ones the platform
    publishes."""
    return MoneyGateImpl(
        storage.get_budget_storage(),
        storage.get_account_storage(),
        storage.get_money_ledger_storage(),
        pager or OperatorPagerLogImpl(),
        plans,
        units,
        options or MoneyGateOptions(),
        clock,
    )


def refuse_open_money(environment: str, managers: Managers) -> None:
    """Outside `local`, a root whose budget gate is not billing's is refused
    at boot: the engine's gate holds a call on its limits alone, and never
    asks who pays, so a tenant with no account would spend on the
    platform's key."""
    if environment == LOCAL:
        return
    gate = managers.budget_gate
    if not isinstance(gate, MoneyGateInterface):
        raise UnsafeConfiguration(
            f"{type(gate).__name__} is not the money gate, and is refused "
            f"when the environment is {environment}"
        )
