"""A session of the support assistant, the kind behind the portal's support
dock, is the request's that asks it and never a worker's. A question left
pending past the stall window is passed over by the maintenance worker's
sweeps, and a loop item that names the session anyway, as an operator's
requeue would, is completed by the runner's claim with no run: no step is
written, and no model is called. The next question takes the session up."""

import asyncio
from datetime import timedelta
from pathlib import Path

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_sessions.kinds import AgentSessionWorkKind, LoopPayload
from acme.om.agents.types.request import Question, Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import RequestContext
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkStatus
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.main import build_runner
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings
from acme.workers.maintenance.agent_sessions import StalledOptions, StalledSessionsSweep
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop

from contracts.doubles import APP
from contracts.loops import reply, said
from contracts.platform_agents import CORPUS


async def test_the_runners_claim_and_the_sweeps_pass_over_a_support_assistants_session(
    tmp_path: Path,
) -> None:
    storage, infra = StorageMemoryImpl(), InfraLocalImpl(tmp_path)
    providers = scripted_model_providers()
    agents = PlatformAgents(corpus=CORPUS)
    container = RunnerContainer.over(
        AgentSessionRunnerSettings.model_validate(
            {"_env_file": None, "environment": "test", "runner_id": "runner-test"}
        ),
        storage,
        infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), providers),
        platform_agents=agents,
    )
    managers = container.managers
    rctx = RequestContext(request_id=new_id(), app=APP)
    owner, _ = await managers.tenancy.bootstrap(rctx, "Ajax", "ajax", "ann@example.test", "Ann")
    await seed_platform(storage, managers, owner)
    agent_session_id = new_id()
    start = Start(id=agent_session_id, kind=kinds.SUPPORT_ASSISTANT, title="Support")
    question = Question(
        id=new_id(), agent_session_id=agent_session_id, text="Why is it queued?", start=start
    )
    # The question is written, and the request that asked it died before its
    # loop ran: the session is left with a pending input and no loop item.
    await managers.agents.ask(owner, question)
    before = await managers.agent_steps.get_agent_steps(owner, agent_session_id, 0, 200)

    # The stalled sweep, past its window, reads the session and passes it by.
    later = utcnow() + StalledOptions().stall_after + timedelta(minutes=1)
    stalled = StalledSessionsSweep(
        managers.agent_sessions,
        managers.work,
        managers.tenancy,
        StalledOptions(),
        managers.kinds,
        clock=lambda: later,
    )
    assert await stalled(rctx) == 1, "the sweep read the session"
    maintenance = build_loop(WorkerContainer.for_tests(storage, infra, platform_agents=agents))
    await maintenance._sweep_once()  # pyright: ignore[reportPrivateUsage]
    runner = build_runner(container)
    await runner._recover_once()  # pyright: ignore[reportPrivateUsage]
    assert not await managers.work.has_open(owner, AgentSessionWorkKind.LOOP, agent_session_id)

    # A loop item that names it anyway is the runner's to complete, unrun.
    now = utcnow()
    item = await managers.work.enqueue(
        owner,
        WorkItem(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=owner.user_id,
            updated_by=owner.user_id,
            kind=AgentSessionWorkKind.LOOP,
            target_id=agent_session_id,
            idempotency_key=new_id(),
            request_id=rctx.request_id,
            payload=LoopPayload().model_dump(mode="json"),
            available_at=now,
        ),
    )
    running = asyncio.create_task(runner.run())
    for _ in range(100):
        if (await managers.work.get_item(owner, item.id)).status is WorkStatus.DONE:
            break
        await asyncio.sleep(0.02)
    runner.stop()
    await running

    assert (await managers.work.get_item(owner, item.id)).status is WorkStatus.DONE
    after = await managers.agent_steps.get_agent_steps(owner, agent_session_id, 0, 200)
    assert [step.id for step in after.items] == [step.id for step in before.items]
    twin = providers.get(ProviderName.ANTHROPIC)
    assert twin.calls == []  # pyright: ignore[reportAttributeAccessIssue]

    # The next question takes the session up, in its request.
    twin.add(reply(said("It waits on a host.")))  # pyright: ignore[reportAttributeAccessIssue]
    await managers.agents.ask(
        owner, Question(id=new_id(), agent_session_id=agent_session_id, text="And now?")
    )
    run = await managers.loop.run(owner, agent_session_id)
    assert run.end is RunEnd.ENDED
