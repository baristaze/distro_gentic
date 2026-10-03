"""One router module per hosted namespace, mounted under /v1 by the app.

`all_routers(namespaces)` answers the routers of the namespaces named, or of
every hosted one when none is named. That is the first form of a split: the
same image, told by `ACME_NAMESPACES` which routers to mount, serves one
namespace as a service of its own, and no code changes."""

from collections.abc import Sequence

from fastapi import APIRouter

from acme.services.api.realtime import control, socket
from acme.services.api.routers import (
    admin,
    agent_sessions,
    automations,
    benchmarks,
    budgets,
    events,
    fleet,
    hosts,
    intake,
    knowledge,
    ledgers,
    matrix,
    matrix_operator,
    media,
    notifications,
    playbooks,
    projects,
    provider_keys,
    relay,
    tenancy,
    tools,
    watch,
)

HOSTED: dict[str, tuple[APIRouter, ...]] = {
    # The operator plane is tenancy's: it lists and deletes orgs, and the
    # platform's own operator routes ride beside it.
    "tenancy": (tenancy.router, admin.router, fleet.router),
    # The realtime channel is the events stream pushed; its replay is `/events`.
    "events": (events.router, socket.router),
    "media": (media.router,),
    # Sessions with an agent; their loops run in the session runner.
    "agent_sessions": (agent_sessions.router,),
    # A tenant's pools and hosts, and a host's own calls: enroll, rotate,
    # beat, and claim.
    "hosts": (hosts.router,),
    # The exec work a host holds and its control stream: a host's own calls,
    # each opened from inside its wall.
    "relay": (relay.router, control.router),
    # A tenant's connections to the systems whose events reach its sessions.
    "intake": (intake.router,),
    # What a tenant may spend: a budget's amount, which a raise of wakes the
    # sessions waiting on it.
    "budgets": (budgets.router,),
    # The tenant's automations, and its automation principal and its grant.
    "automations": (automations.router,),
    # A tenant's projects, each bound to its repository, and the fetch
    # credential the platform reads that repository with.
    "projects": (projects.router,),
    # What sessions recall, and the procedures they follow.
    "knowledge": (knowledge.router,),
    "playbooks": (playbooks.router,),
    # The tenant's layer of tool policy.
    "tools": (tools.router,),
    # What waits on a person, and their mark that they read it.
    "notifications": (notifications.router,),
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
    # The operators' read of a tenant's ledger.
    "billing": (ledgers.router,),
}
"""Every namespace this image hosts, and the routers that serve it."""


def all_routers(namespaces: Sequence[str] = ()) -> list[APIRouter]:
    """The routers to mount; a name this image does not host refuses the boot."""
    unknown = sorted(set(namespaces) - set(HOSTED))
    if unknown:
        raise ValueError(
            f"ACME_NAMESPACES names {', '.join(unknown)}; this image hosts {', '.join(HOSTED)}"
        )
    chosen = namespaces or tuple(HOSTED)
    return [router for name in HOSTED if name in chosen for router in HOSTED[name]]
