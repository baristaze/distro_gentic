"""The support assistant, the kind behind the portal's support dock, runs its
loop in the request that asks it. It passes the engine's check for such a
kind with every reader a product joins to it, where the platform assistant,
which hands work on, would not; a product's reader that a request may not
hold refuses the platform at start. A session of it starts by a question
alone: an agent automation that would start one is refused when saved, and
a connector is never attached to it."""

from datetime import timedelta
from pathlib import Path

import pytest
from unit.test_platform_agents import shipped_catalog

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agent_automations.types.agent_automation import (
    Action,
    ActionKind,
    AgentAutomation,
    Limits,
    Trigger,
    TriggerKind,
)
from acme.om.agents.rules import request_kind_breaches
from acme.om.agents.types.kind import RunsIn
from acme.om.base import OmBase as Record
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.exceptions import UnsafeConfiguration, ValidationFailed
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.kinds.platform_assistant.kind import PLATFORM_ASSISTANT_KIND
from acme.om.platform_agents.kinds.support_assistant.kind import SUPPORT_ASSISTANT_KIND
from acme.om.platform_agents.tools.base import NativeToolImpl
from acme.om.platform_root import PlatformRootOptions, ProductKinds, build_platform_managers
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.rules import DEFAULT_CEILINGS
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec
from acme.om.windows.rules import READ_TOOL_OUTPUT

from contracts.loops import reply, said
from contracts.platform_agents import CORPUS, platform_over


class Nothing(ToolInput):
    pass


class Tally(Record):
    count: int


def a_reader(name: str, authorization_class: str = ToolClass.READ) -> type[NativeToolImpl]:
    """A product's tool for the assistants' slot, of `authorization_class`."""

    class ReaderImpl(NativeToolImpl):
        SPEC = ToolSpec(
            name=name,
            description="Counts what the product holds.",
            input_model=Nothing,
            output_model=Tally,
            timeout=timedelta(seconds=10),
            authorization_class=authorization_class,
            effect=Effect.READ_ONLY,
            interruptible=True,
            mode=ToolMode.SYNC,
        )

        async def run(
            self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
        ) -> Record:
            return Tally(count=3)

    return ReaderImpl


# Check 1: the dock's kind passes the engine's check for a request kind.


def test_the_support_assistant_passes_the_engines_check_for_a_request_kind() -> None:
    specs = {tool.spec.name: tool.spec for tool in shipped_catalog()}

    assert SUPPORT_ASSISTANT_KIND.runs_in is RunsIn.REQUEST
    assert request_kind_breaches(SUPPORT_ASSISTANT_KIND, specs, DEFAULT_CEILINGS) == ()
    # The platform assistant hands work to a software engineer in a session
    # of its own, which a request may not start: the dock has a kind of its
    # own, and the assistant stays a worker's.
    assert PLATFORM_ASSISTANT_KIND.runs_in is RunsIn.WORKER
    as_request = PLATFORM_ASSISTANT_KIND.model_copy(update={"runs_in": RunsIn.REQUEST})
    breaches = request_kind_breaches(as_request, specs, DEFAULT_CEILINGS)
    assert f"{kinds.HAND_OFF} starts a session, a sub-agent's or a handoff's" in breaches
    # It reads what the assistant reads, and reads back a result its window
    # keeps outside it, as every kind that calls tools does.
    handed = {kinds.HAND_OFF}
    read_back = {READ_TOOL_OUTPUT}
    assert (
        set(SUPPORT_ASSISTANT_KIND.tools) == set(PLATFORM_ASSISTANT_KIND.tools) - handed | read_back
    )


async def test_a_products_reader_joins_the_support_assistant_and_one_a_request_refuses_stops_the_start(
    tmp_path: Path,
) -> None:
    product = ProductKinds(
        tools=lambda _managers: (a_reader("read_tally")(),), assistant_tools=("read_tally",)
    )
    platform = platform_over(tmp_path, product_kinds=product)
    agent_session_id = await platform.ask(kinds.SUPPORT_ASSISTANT, "How many tallies?")
    platform.anthropic.add(reply(said("Three.")))

    run = await platform.managers.loop.run(platform.owner, agent_session_id)

    assert run.outcome is not None and run.outcome.value == "succeeded"
    (call,) = platform.anthropic.calls
    assert "read_tally" in {tool.name for tool in call.tools}
    # A tool that hands work on is one the assistant may call and a request
    # may not: the platform refuses to start with it in the dock's kind.
    handing = ProductKinds(
        tools=lambda _managers: (a_reader("hand_tally_on", ToolClass.SPAWN)(),),
        assistant_tools=("hand_tally_on",),
    )
    refused = "hand_tally_on is a spawn tool, and the support_assistant only reads"
    with pytest.raises(UnsafeConfiguration, match=refused):
        build_platform_managers(
            StorageMemoryImpl(),
            InfraLocalImpl(tmp_path),
            platform_root_options=PlatformRootOptions(
                platform_agents=PlatformAgents(corpus=CORPUS), product_kinds=handing
            ),
        )


# Check 5: a session of a request kind starts by a question alone, so no
# agent automation starts one and holds its run open with no worker to run it.


async def test_an_agent_automation_never_starts_a_kind_whose_loop_runs_in_the_request(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    now = utcnow()

    def starting(agent_kind: str) -> AgentAutomation:
        return AgentAutomation(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=platform.owner.user_id,
            updated_by=platform.owner.user_id,
            name="answer on a comment",
            trigger=Trigger(kind=TriggerKind.EVENT, arrivals=("comment",)),
            action=Action(
                kind=ActionKind.START_SESSION,
                brief="Answer the comment.",
                agent_kind=agent_kind,
                title="a comment",
            ),
            limits=Limits(cost_cap_micros=10**9, run_cap_micros=10**8, rate=10, concurrency=10),
        )

    with pytest.raises(ValidationFailed, match="runs its loop in the request that asks it"):
        await platform.agent_automations.create_agent_automation(
            platform.owner, starting(kinds.SUPPORT_ASSISTANT)
        )
    made = await platform.agent_automations.create_agent_automation(
        platform.owner, starting(kinds.PLATFORM_ASSISTANT)
    )
    assert made.action.agent_kind == kinds.PLATFORM_ASSISTANT
