"""A session on the cloud pool's VMs, on this machine's Lima, beside the
local stack `make up` starts: the runner that drives the pool, and one
session for it to run.

    make cloud-pool            # the runner, until Ctrl-C
    make cloud-pool-session    # one session, in a second terminal

The platform's kinds ask for a container, so a session of theirs never
reaches the pool. This script declares a kind of its own, `vm_assistant`,
which runs commands in a VM of its session's own, with open egress, its
directory kept as a snapshot at the end of each loop. Only the two
processes this script starts know it: the runner, and the process that
starts the session. The API, the portal, and every image know none of it.

`session` starts one session of that kind as the owner of the org the slug
names, which `make up` seeds, says the message, and waits for the runner to
end the loop. Then it prints each step, what each command printed, and the
snapshot the loop kept. The model is the one the runner's settings name.
The scripted twin, with `deployment/local/cloud-pool-turns.json`, runs one
command and answers, with no key.

Every import of the platform waits for the trust store, as the runner's own
entry point installs it before anything binds ssl."""

import argparse
import asyncio
import dataclasses
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acme.om.platform_root import PlatformManagers, ProductKinds
    from acme.om.tools.tool import ToolInterface
    from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

KIND = "vm_assistant"
LOOP_ENDS_WITHIN = timedelta(minutes=20)
"""How long `session` waits on the loop: a first VM boots the pool's image."""


def kinds(settings: AgentSessionRunnerSettings) -> ProductKinds:
    """The product's kinds and this script's `vm_assistant`. The platform's
    `run_command` ships with its agents, which a corpus root turns on;
    without one, this script brings it."""
    from acme.infra.agent_workspaces import (
        Durability,
        EgressMode,
        EgressPolicy,
        IsolationMode,
        IsolationSpec,
    )
    from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
    from acme.om.attribution.types.authority import AuthorityMode
    from acme.om.platform_agents.tools.code import RunCommandImpl
    from acme.om.product_kinds import PRODUCT_KINDS
    from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
    from acme.om.tools.types.tool import ToolClass

    vm_assistant = AgentKind(
        name=KIND,
        version=1,
        tools=(RunCommandImpl.SPEC.name,),
        done_rule=DoneRule.ANSWER,
        authority=AuthorityMode.DELEGATED,
        tree=TreeLimits(height=1, count=0),
        prompts=(
            "You answer a person's question. Run a command in the workspace with "
            "run_command when the answer needs one, then answer in one sentence.",
        ),
        policy=ToolPolicyLayer(
            rules=(ToolPolicyRule(authorization_class=ToolClass.EXECUTE, decision=Decision.ALLOW),)
        ),
        # Lima closes no VM's egress, so the pool refuses a closed one there.
        isolation=IsolationSpec(
            mode=IsolationMode.VM,
            egress=EgressPolicy(mode=EgressMode.OPEN),
            durability=Durability.SNAPSHOT,
        ),
    )
    shipped = settings.corpus_root is not None

    def tools(managers: Callable[[], PlatformManagers]) -> tuple[ToolInterface, ...]:
        own: tuple[ToolInterface, ...] = () if shipped else (RunCommandImpl(),)
        return (*PRODUCT_KINDS.tools(managers), *own)

    return dataclasses.replace(
        PRODUCT_KINDS, agents=(*PRODUCT_KINDS.agents, vm_assistant), tools=tools
    )


def runner() -> int:
    """The session runner's own entry, with this script's kind beside the
    product's: it claims every loop of its lane."""
    from acme.om.platform_root import PlatformPorts
    from acme.workers.agent_session_runner.main import main
    from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

    return main(["serve"], ports=PlatformPorts(kinds=kinds(AgentSessionRunnerSettings())))


async def session(message: str, slug: str) -> int:
    """One session of the kind, started as the org's owner, its message
    said; then its first loop's steps, once the runner ends it."""
    from acme.om.agent_steps.rules import message_step
    from acme.om.agent_steps.types.agent_step import AgentStepType
    from acme.om.agents.types.request import Start
    from acme.om.base import new_id, utcnow
    from acme.om.context import AppContext, AppType, RequestContext
    from acme.om.platform_root import PlatformPorts
    from acme.workers.agent_session_runner.container import RunnerContainer
    from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

    # This process starts no VM: the runner's pool runs the loop.
    settings = AgentSessionRunnerSettings(vms_backend="none", cloud_pool_image="")
    container = RunnerContainer.build(settings, ports=PlatformPorts(kinds=kinds(settings)))
    await container.start()
    try:
        managers = container.managers
        rctx = RequestContext(
            request_id=new_id(), app=AppContext(type=AppType.CLI, version="cloud-pool@local")
        )
        org = await container.storage.get_tenancy_storage().read_org_by_slug(slug)
        if org is None:
            print(f"no org {slug}; `make up` seeds it", file=sys.stderr)
            return 1
        owner = await managers.tenancy.delegated_context(rctx, org.id, org.created_by)
        started = await managers.agents.start_agent_session(
            owner, Start(id=new_id(), kind=KIND, title="a VM of its own")
        )
        asked = message_step(new_id(), utcnow(), started.id, owner, message)
        await managers.agent_sessions.receive(owner, started.id, [asked])
        print(f"session {started.id}: waiting on the runner of `make cloud-pool`", flush=True)
        deadline = time.monotonic() + LOOP_ENDS_WITHIN.total_seconds()
        while True:
            page = await managers.agent_steps.get_agent_steps(owner, started.id, 0, 200)
            ended = [s for s in page.items if s.type is AgentStepType.LOOP_ENDED]
            if ended or time.monotonic() > deadline:
                break
            await asyncio.sleep(2)
        for step in page.items:
            printed = ""
            if step.type is AgentStepType.TOOL_RESPONSE:
                printed = step.content.model_dump_json(include={"blocks"})[:1500]
            print(f"{step.seq:>3} {step.type.value:<16} {printed}")
        for kept in await managers.agent_workspaces.kept_snapshots(owner, started.id):
            print(f"kept: {kept.reference}, on a host: {kept.on_host}")
        if not ended:
            print(f"no loop ended within {LOOP_ENDS_WITHIN}", file=sys.stderr)
            return 1
        print(f"loop ended: {ended[-1].header.model_dump_json()}")
        return 0
    finally:
        await container.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloud_pool.py")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("runner", help="the session runner, with the cloud pool's kind")
    p_session = sub.add_parser("session", help="start one session in a VM and wait on its loop")
    p_session.add_argument(
        "--slug", required=True, help="the org, by its slug, whose owner starts the session"
    )
    p_session.add_argument("message", help="what the session is asked")
    args = parser.parse_args(argv)
    from acme.infra.trust import install_trust_store

    install_trust_store()
    if args.command == "runner":
        return runner()
    return asyncio.run(session(args.message, args.slug))


if __name__ == "__main__":
    sys.exit(main())
