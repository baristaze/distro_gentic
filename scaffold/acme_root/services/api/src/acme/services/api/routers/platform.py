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
    agent_knowledge,
    agent_playbooks,
    agent_projects,
    agent_sessions,
    benchmarks,
    connectors,
    evidence,
    exec_relay,
    hosts,
    intake,
    levers,
    matrix,
    park_alerts,
    placement,
    platform_agents,
    retention,
    spend_budgets,
    tools,
    trust,
    watch,
)

BESIDE: dict[str, tuple[APIRouter, ...]] = {
    # What waits on a person across sessions reads the same sessions.
    "agent_sessions": (agent_sessions.approvals,),
}
"""The platform's routers that a namespace of the engine's serves beside its
own, each in that namespace's router module."""

PLATFORM_HOSTED: dict[str, tuple[APIRouter, ...]] = {
    # What a session ran to show its work, and what it delivered.
    "evidence": (evidence.router,),
    # A check of an agent project's policy run with no agent, as CI asks for one.
    "platform_agents": (platform_agents.router,),
    # A tenant's pools and hosts, and a host's own calls: enroll, rotate,
    # beat, and claim; and a product's claimant's, through the same path,
    # with its control stream.
    "hosts": (hosts.router, hosts.claimants, control.claimants, hosts.operator),
    # The exec work a host holds and its control stream: a host's own calls,
    # each opened from inside its wall.
    "exec_relay": (exec_relay.router, control.router),
    # A tenant's connections to the systems whose events reach its sessions.
    "intake": (intake.router,),
    # What a tenant may spend: a budget's amount, which a raise of wakes the
    # sessions waiting on it, and what each budget's window spent.
    "spend_budgets": (spend_budgets.router, spend_budgets.usage),
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
    "matrix": (matrix.router, matrix.operator),
    # A tenant's own keys to its model providers, written and never read
    # back; and the operators' read of a session's shape, and its content
    # under a grant.
    "trust": (trust.router, trust.operator),
    # The operators' read of the platform's benchmarks and their trend.
    "benchmarks": (benchmarks.operator,),
    # The tenant's writes that clear a park on its money, and the operators'
    # read of a tenant's ledger and their grant of units.
    "agent_billing": (agent_billing.router, agent_billing.operator),
    # The operators' write of a tenant's fair share, and their read of where
    # its sessions and its hosts stand.
    "placement": (placement.operator,),
    # The operators' read of which levers a tenant's sessions reached
    # before they stalled.
    "levers": (levers.operator,),
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
