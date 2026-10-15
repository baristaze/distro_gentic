"""The platform's routers beside the engine's (`routers.HOSTED`): the
routers that ride beside a namespace of the engine's, each namespace the
platform adds, and the product's (`acme.services.api.product_api`)."""

from collections.abc import Mapping

from fastapi import APIRouter

from acme.services.api import product_api
from acme.services.api.realtime import control
from acme.services.api.routers import (
    agent_automations,
    agent_billing,
    agent_fleet,
    agent_knowledge,
    agent_playbooks,
    agent_projects,
    approvals,
    benchmarks,
    budgets,
    claimants,
    connectors,
    evidence,
    exec_relay,
    hosts,
    intake,
    matrix,
    matrix_operator,
    park_alerts,
    provider_keys,
    retention,
    spend_ledgers,
    tools,
    usage,
    validations,
    watch,
)

BESIDE: dict[str, tuple[APIRouter, ...]] = {
    # The platform's own operator routes ride beside tenancy's operator plane.
    "tenancy": (agent_fleet.router,),
    # What waits on a person across sessions reads the same sessions.
    "agent_sessions": (approvals.router,),
}
"""The platform's routers that a namespace of the engine's serves beside its
own."""

PLATFORM_HOSTED: dict[str, tuple[APIRouter, ...]] = {
    # What a session ran to show its work, and what it delivered.
    "evidence": (evidence.router,),
    # A check of an agent project's policy run with no agent, as CI asks for one.
    "platform_agents": (validations.router,),
    # A tenant's pools and hosts, and a host's own calls: enroll, rotate,
    # beat, and claim; and a product's claimant's, through the same path.
    "hosts": (hosts.router, claimants.router),
    # The exec work a host holds and its control stream: a host's own calls,
    # each opened from inside its wall.
    "exec_relay": (exec_relay.router, control.router),
    # A tenant's connections to the systems whose events reach its sessions.
    "intake": (intake.router,),
    # What a tenant may spend: a budget's amount, which a raise of wakes the
    # sessions waiting on it, and what each budget's window spent.
    "budgets": (budgets.router, usage.router),
    # The tenant's agent automations, and its agent automation principal and its grant.
    "agent_automations": (agent_automations.router,),
    # A tenant's agent projects, each bound to its repository, and the fetch
    # credential the platform reads that repository with.
    "agent_projects": (agent_projects.router,),
    # What sessions recall, and the procedures they follow, each invoked
    # into a session or pinned to a kind as its kind manual.
    "agent_knowledge": (agent_knowledge.router,),
    "agent_playbooks": (agent_playbooks.router, agent_playbooks.pins),
    # A tenant's own MCP servers, reviewed and attached to its kinds.
    "connectors": (connectors.router,),
    # The tenant's layer of tool policy.
    "tools": (tools.router,),
    # How long the tenant keeps its sessions' content and shape, and one
    # session's content erased before then.
    "retention": (retention.router,),
    # What waits on a person, and their mark that they read it.
    "park_alerts": (park_alerts.router,),
    # A live read of a session by a scoped handle, and take control, a
    # command by hand, and give back, each the person's.
    "watch": (watch.router,),
    # What a tenant on its own keys may choose of the model matrix, and its
    # choices; and the operators' stage, publish, and read of a version.
    "matrix": (matrix.router, matrix_operator.router),
    # A tenant's own keys to its model providers, written and never read back.
    "trust": (provider_keys.router,),
    # The operators' read of the platform's benchmarks and their trend.
    "benchmarks": (benchmarks.router,),
    # The tenant's writes that clear a park on its money, and the operators'
    # read of a tenant's ledger and their grant of units.
    "agent_billing": (agent_billing.router, spend_ledgers.router),
}
"""Every namespace the platform adds, and the routers that serve it."""


def with_platform(hosted: Mapping[str, tuple[APIRouter, ...]]) -> dict[str, tuple[APIRouter, ...]]:
    """`hosted`, each namespace with the platform's routers beside its own,
    then the platform's namespaces, then the product's. A name hosted twice
    is refused at boot."""
    served = {name: (*routers, *BESIDE.get(name, ())) for name, routers in hosted.items()}
    for extra in (PLATFORM_HOSTED, product_api.PRODUCT_API.hosted()):
        for name, routers in extra.items():
            if name in served:
                raise ValueError(f"namespace {name} is hosted twice")
            served[name] = routers
    return served
