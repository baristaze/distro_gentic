"""Playbooks, as the platform runs them: a playbook's gates only narrow the
session's policy, whatever the policy beneath says, a job's included, and
only a person publishes or invokes one; an agent's call does neither."""

import itertools
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.budget_storage import make_budget
from contracts.intake import Wired, wired
from contracts.loops import ASSISTANT, BUILDER, DELIVERY, Clock, call, loop_over, reply, said, use
from pydantic import ValidationError

from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.budgets.types.budget import BudgetScopeKind
from acme.om.context import Role
from acme.om.exceptions import NotAuthorized
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.playbooks.rules import GATES_KEY, narrowed, skill_md
from acme.om.playbooks.types.playbook import Playbook, PlaybookDraft, PlaybookGate
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.root import Managers
from acme.om.steps.types.header import ParkReason, ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.rules import decide
from acme.om.tools.types.policy import Decision, PolicyCall, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import Effect
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.impl.gate import CallGateBudgetImpl

TOOLS = ("lookup", "call_api", "publish")
CLASSES = ("read", "execute", "integration")


def gate(decision: Decision, tool: str | None = None, cls: str | None = None) -> PlaybookGate:
    return PlaybookGate(tool=tool, authorization_class=cls, decision=decision)


def draft(*gates: PlaybookGate, name: str = "answer-a-question") -> PlaybookDraft:
    return PlaybookDraft(
        name=name,
        description="Answer a question from the records.",
        body="## Steps\n\n1. Look the answer up.\n2. Say it.",
        gates=gates,
    )


@pytest.fixture
def platform(tmp_path: Path) -> Wired:
    return wired(tmp_path)


def test_a_gate_never_allows() -> None:
    with pytest.raises(ValidationError):
        gate(Decision.ALLOW, tool="lookup")
    with pytest.raises(ValidationError):
        PlaybookGate(decision=Decision.DENY)


def test_gates_only_narrow_whatever_the_policy_beneath_decides() -> None:
    # Every call shape, under every decision the kind's defaults, the
    # tenant's layer, and the platform's ceilings can reach for it, and
    # every pair of gates a playbook can hold: with the gates, a call is
    # never decided less strictly than without them.
    gates = [
        gate(decision, tool=tool)
        for decision in (Decision.APPROVE, Decision.DENY)
        for tool in TOOLS
    ] + [
        gate(decision, cls=cls) for decision in (Decision.APPROVE, Decision.DENY) for cls in CLASSES
    ]
    decisions = list(Decision)
    checked = 0
    for tool, cls in itertools.product(TOOLS, CLASSES):
        call = PolicyCall(tool=tool, authorization_class=cls, effect=Effect.UNSAFE)
        for kind_d, tenant_d, ceiling_d in itertools.product(decisions, decisions, decisions):
            defaults = PolicyLayer(rules=(PolicyRule(authorization_class=cls, decision=kind_d),))
            tenant = PolicyLayer(rules=(PolicyRule(tool=tool, decision=tenant_d),))
            ceilings = PolicyLayer(rules=(PolicyRule(decision=ceiling_d),))
            decided = decide(call, defaults, tenant, ceilings)
            for chosen in itertools.combinations(gates, 2):
                stands = narrowed(decided, chosen, tool, cls)
                assert stands.strictness >= decided.strictness, (call, chosen)
                checked += 1
    assert checked > 10_000


def test_a_version_is_an_agent_skills_brief_with_its_gates_in_the_metadata() -> None:
    playbook = Playbook(
        id=new_id(),
        created_at=utcnow(),
        name="release-a-build",
        version=3,
        description='Cut a build: "fast", then hand it over.',
        body="## Steps",
        gates=(gate(Decision.APPROVE, tool="publish"),),
        published_by=new_id(),
    )
    text = skill_md(playbook)
    head, body = text.split("\n---\n", 1)
    lines = head.splitlines()
    assert lines[0] == "---" and lines[1] == "name: release-a-build"
    assert json.loads(lines[2].removeprefix("description: ")) == playbook.description
    (gates_line,) = [line for line in lines if line.strip().startswith(GATES_KEY)]
    gates = json.loads(json.loads(gates_line.split(": ", 1)[1]))
    assert gates == [{"tool": "publish", "decision": "approve"}]
    assert body.strip() == "## Steps"


async def test_only_a_person_publishes_and_each_publish_is_the_next_version(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    with pytest.raises(NotAuthorized):
        await platform.playbooks.publish(await platform.agents_call(author), draft())
    first = await platform.playbooks.publish(author, draft())
    second = await platform.playbooks.publish(author, draft(gate(Decision.DENY, tool="lookup")))
    assert (first.version, second.version) == (1, 2)
    assert (await platform.playbooks.get_playbook(author, first.name)) == second


async def test_a_deny_gate_refuses_a_call_the_policy_beneath_allows(platform: Wired) -> None:
    session_id = await platform.start()
    await platform.playbooks.publish(platform.owner, draft(gate(Decision.DENY, tool="lookup")))
    with pytest.raises(NotAuthorized):
        await platform.playbooks.invoke(
            await platform.agents_call(platform.owner), session_id, "answer-a-question"
        )
    await platform.playbooks.invoke(platform.owner, session_id, "answer-a-question")
    platform.anthropic.add(reply(use("lookup")), reply(said("I may not look it up.")))
    assert (await platform.loops.run(platform.owner, session_id)).end is RunEnd.ENDED
    assert platform.lookup.ran_as == []
    (answer,) = [s for s in await platform.history(session_id) if s.type is StepType.TOOL_RESPONSE]
    assert isinstance(answer.header, ToolResponseHeader)
    assert answer.header.failure is ToolFailure.DENIED
    # The brief arrived as the invoker's message, in the standard's form.
    (brief,) = [s for s in await platform.history(session_id) if s.type is StepType.MESSAGE]
    assert brief.as_text().startswith("---\nname: answer-a-question\n")


async def test_an_approve_gate_holds_a_call_for_a_person(platform: Wired) -> None:
    session_id = await platform.start()
    await platform.playbooks.publish(platform.owner, draft(gate(Decision.APPROVE, cls="read")))
    await platform.playbooks.invoke(platform.owner, session_id, "answer-a-question")
    platform.anthropic.add(reply(use("lookup")))
    run = await platform.loops.run(platform.owner, session_id)
    assert run.end is RunEnd.PARKED and run.park is not None
    assert run.park.reason is ParkReason.PERSON
    assert platform.lookup.ran_as == []
    (request,) = [s for s in await platform.history(session_id) if s.type is StepType.TOOL_REQUEST]
    await platform.managers.tools.decide_call(platform.owner, session_id, request.seq, approve=True)
    platform.anthropic.add(reply(said("The total is in.")))
    assert (await platform.loops.run(platform.owner, session_id)).end is RunEnd.ENDED
    assert platform.lookup.ran_as == [platform.owner.user_id]


async def test_an_invocation_is_once_a_version(platform: Wired) -> None:
    session_id = await platform.start()
    await platform.playbooks.publish(platform.owner, draft(gate(Decision.DENY, tool="lookup")))
    first = await platform.playbooks.invoke(platform.owner, session_id, "answer-a-question")
    again = await platform.playbooks.invoke(platform.owner, session_id, "answer-a-question")
    assert again == first
    messages = [s for s in await platform.history(session_id) if s.type is StepType.MESSAGE]
    assert len(messages) == 1
    assert await platform.playbooks.gates_of(platform.owner, session_id) == (
        gate(Decision.DENY, tool="lookup"),
    )
    other = await platform.start()
    assert await platform.playbooks.gates_of(platform.owner, other) == ()


async def test_a_deny_gate_invoked_while_a_job_is_held_refuses_it_and_releases_its_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A playbook a person invokes once a spending job passed its gates,
    while the budget gate holds it, still refuses the job before its tool
    runs: the job never starts, and its hold is released, never counted."""
    storage = StorageMemoryImpl()
    layer = PlaybooksLayer(storage)
    gates: list[CallGateBudgetImpl] = []

    def call_gate(managers: Managers, clock: Clock) -> CallGateInterface:
        gates.append(
            CallGateBudgetImpl(
                managers.budget_gate,
                managers.pricing,
                managers.agent_sessions,
                SessionProjectsBoundImpl(storage.get_project_storage()),
                clock=clock,
            )
        )
        return gates[0]

    loop = loop_over(
        tmp_path,
        storage=storage,
        kinds=(ASSISTANT, DELIVERY, BUILDER),
        call_gate=call_gate,
        tools_layer=layer.tools,
    )
    playbooks = layer.build(loop.managers)
    session_id = await loop.start("builder")
    line = await loop.managers.budgets.create_budget(
        loop.owner, make_budget(BudgetScopeKind.SESSION, str(session_id), cost_micros=50_000_000)
    )
    await playbooks.publish(loop.owner, draft(gate(Decision.DENY, tool="compute")))
    hold = gates[0].authorize_job

    async def held_then_invoked(*args: Any) -> UUID:
        held = await hold(*args)
        await playbooks.invoke(loop.owner, session_id, "answer-a-question")
        return held

    monkeypatch.setattr(gates[0], "authorize_job", held_then_invoked)
    await loop.say(session_id, "Start it.")
    loop.anthropic.add(reply(call("compute", q="everything")), reply(said("I may not start it.")))

    assert (await loop.loops.run(loop.owner, session_id)).end is RunEnd.ENDED

    assert loop.jobs["compute"].started == {}, "no job started"
    (answer,) = [s for s in await loop.history(session_id) if s.type is StepType.TOOL_RESPONSE]
    assert isinstance(answer.header, ToolResponseHeader)
    assert answer.header.failure is ToolFailure.DENIED
    spend = await loop.managers.budgets.get_spend(loop.owner, line.id)
    assert spend.held_cost_micros == 0, "the hold settled"
    assert spend.spent_cost_micros < 7_200_000, "released: the model's calls alone count"
