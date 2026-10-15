"""The `operations` toolset: read the tenant's pools of hosts and what each
offers, and its budgets and what they spent."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import HostStatus
from acme.om.platform_agents import kinds
from acme.om.platform_agents.tools.base import HOSTS_MAX, LIST_MAX, NativeToolImpl, PageInput
from acme.om.spend_budgets import SpendBudgetsManagerInterface
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec


class Offer(OmBase):
    """What a host offers, as it advertised itself."""

    os: str
    shell: str
    capabilities: tuple[str, ...]
    isolation_modes: tuple[str, ...]
    exec_version: int


class OfferingHost(OmBase):
    host_id: UUID
    name: str
    online: bool
    last_seen_at: datetime
    offers: Offer


class PoolHosts(OmBase):
    pool_id: UUID
    name: str
    region: str
    hosts: tuple[OfferingHost, ...]  # its live hosts, the one seen last first
    more_hosts: bool


class Hosts(OmBase):
    pools: tuple[PoolHosts, ...]


class NoInput(ToolInput):
    pass


class ListHostsImpl(NativeToolImpl):
    """Lists the tenant's own pools of hosts, each with its live hosts and
    what each offers: its operating system and shell, its capabilities, the
    isolation it can give, and the version of work it reads, as the host
    advertised them. A machine the cloud pool runs for one session is the
    platform's, never listed."""

    SPEC = ToolSpec(
        name=kinds.LIST_HOSTS,
        description=(
            "Lists the tenant's pools of hosts, each with its hosts, whether each is online, "
            "and what each offers: its operating system and shell, its capabilities, and the "
            "isolation it can give a workspace. A pool lists its first 20 hosts."
        ),
        input_model=NoInput,
        output_model=Hosts,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, hosts: Callable[[], HostsManagerInterface]) -> None:
        self._hosts = hosts

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        hosts = self._hosts()
        pools: list[PoolHosts] = []
        for pool in (await hosts.get_pools(ctx))[:LIST_MAX]:
            live = await hosts.get_hosts(ctx, pool.id)
            pools.append(
                PoolHosts(
                    pool_id=pool.id,
                    name=pool.name,
                    region=str(pool.region),
                    hosts=tuple(_offering(status) for status in live[:HOSTS_MAX]),
                    more_hosts=len(live) > HOSTS_MAX,
                )
            )
        return Hosts(pools=tuple(pools))


def _offering(status: HostStatus) -> OfferingHost:
    host = status.host
    told = host.advertisement
    return OfferingHost(
        host_id=host.id,
        name=host.name,
        online=status.online,
        last_seen_at=host.last_seen_at,
        offers=Offer(
            os=told.os,
            shell=told.shell,
            capabilities=told.capabilities,
            isolation_modes=tuple(mode.value for mode in told.isolation_modes),
            exec_version=host.exec_version,
        ),
    )


class BudgetSpend(OmBase):
    spend_budget_id: UUID
    scope: str  # what it bounds: the org, an agent project, a person, a session
    key: str
    window: str
    window_seconds: int | None = None
    window_start: datetime
    cost_micros: int | None = None  # its amount, in millionths of the currency
    tokens: int | None = None
    spent_cost_micros: int
    spent_tokens: int
    held_cost_micros: int  # what calls running now reserve


class Spend(OmBase):
    budgets: tuple[BudgetSpend, ...]
    next: UUID | None = None


class ReadSpendImpl(NativeToolImpl):
    """Reads the tenant's budgets, a page at a time, each with what its
    current window spent and what calls running now hold."""

    SPEC = ToolSpec(
        name=kinds.READ_SPEND,
        description=(
            "Reads the tenant's budgets, a page at a time: what each bounds (the org, a "
            "agent_project, a person, or a session), its amount and window, what the window spent so "
            "far, and what calls running now hold. Pass `next` as `after` for the next page."
        ),
        input_model=PageInput,
        output_model=Spend,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, budgets: Callable[[], SpendBudgetsManagerInterface]) -> None:
        self._budgets = budgets

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> OmBase:
        assert isinstance(call_input, PageInput)
        budgets = self._budgets()
        page = await budgets.get_spend_budgets(ctx, call_input.after, call_input.limit)
        read: list[BudgetSpend] = []
        for budget in page.items:
            tally = await budgets.get_spend(ctx, budget.id)
            read.append(
                BudgetSpend(
                    spend_budget_id=budget.id,
                    scope=budget.scope_kind.value,
                    key=budget.scope_key,
                    window=budget.window_kind.value,
                    window_seconds=budget.window_seconds,
                    window_start=tally.window_start,
                    cost_micros=budget.cost_micros,
                    tokens=budget.tokens,
                    spent_cost_micros=tally.spent_cost_micros,
                    spent_tokens=tally.spent_tokens,
                    held_cost_micros=tally.held_cost_micros,
                )
            )
        last = page.items[-1].id if page.has_more and page.items else None
        return Spend(budgets=tuple(read), next=last)
