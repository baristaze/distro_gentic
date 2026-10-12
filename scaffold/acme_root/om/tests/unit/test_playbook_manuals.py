"""A playbook pinned to a kind as its manual. Each new session of the kind
pins the version's brief as its standing text, which renders whole in the
system layer of every request, before and after a compaction, and its
gates into its policy, where they narrow it and never widen it. A session
made before a pin, or a re-pin, keeps the manual it was made with. Only a
person in person who manages the tenant pins, and a pin a session could
not hold whole is refused."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.histories import History
from contracts.loops import ASSISTANT, SONNET, Loop, loop_over, reply, said, use
from contracts.project_storage import make_project

from acme.integrations.model_providers.anthropic import request_body
from acme.integrations.model_providers.calls import ModelCall, ModelReply
from acme.om.agents.types.request import MAX_STANDING, Spawn, Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.context import CredentialKind, RequestContext, Role, build_context
from acme.om.exceptions import (
    NotAuthorized,
    NotFound,
    UnknownAgentKind,
    ValidationFailed,
)
from acme.om.playbooks.manager import PlaybooksManagerInterface
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.playbooks.rules import skill_md
from acme.om.playbooks.types.playbook import Playbook, PlaybookDraft, PlaybookGate
from acme.om.steps.types.content import TextBlock
from acme.om.steps.types.header import ControlCommand, LoopOutcome, ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.windows.rules import DATA_NOTICE, STANDING_LEAD

STEPS = "\n".join(f"{n:03d}. Quote the ledger's line for each total you give." for n in range(200))
"""A tenant's manual for its assistants: past the pinned zone's bound,
which would cut an invoked brief to an excerpt, and within the standing
text's."""


def manual(*gates: PlaybookGate, body: str = STEPS) -> PlaybookDraft:
    return PlaybookDraft(
        name="ledger-manual",
        description="How an assistant answers from the ledger.",
        body=body,
        gates=gates,
    )


def pinned(
    tmp_path: Path, ceilings: PolicyLayer | None = None
) -> tuple[Loop, PlaybooksManagerInterface]:
    storage = StorageMemoryImpl()
    layer = PlaybooksLayer(storage)
    loop = loop_over(
        tmp_path,
        storage=storage,
        ceilings=ceilings,
        tools_layer=layer.tools,
        agents_layer=layer.agents,
    )
    return loop, layer.build(loop.managers)


def main_calls(loop: Loop) -> list[ModelCall]:
    return [call for call in loop.anthropic.calls if call.model == SONNET]


def system(call: ModelCall) -> list[str]:
    return [block.text for block in call.system]


def standing(version: Playbook) -> str:
    """The system layer's block a session made with the version renders."""
    return f"{STANDING_LEAD}\n\n{skill_md(version)}"


async def started(loop: Loop, session_id: UUID | None = None) -> UUID:
    start = Start(id=session_id or new_id(), kind=ASSISTANT.name, title="the ledger")
    return (await loop.managers.agents.start_session(loop.owner, start)).id


async def asked(
    loop: Loop, session_id: UUID, question: str, *replies: ModelReply
) -> list[ModelCall]:
    """The main requests the session's run sent for the question."""
    before = len(main_calls(loop))
    await loop.say(session_id, question)
    loop.anthropic.add(*replies)
    run = await loop.loops.run(loop.owner, session_id)
    assert (run.end, run.outcome) == (RunEnd.ENDED, LoopOutcome.SUCCEEDED)
    return main_calls(loop)[before:]


def prefix(call: ModelCall) -> bytes:
    body = request_body(call)[0]
    return json.dumps([body.get("tools"), body.get("system")]).encode()


# Check 2: a manual renders whole in the system layer of every request of a
# new session of its kind, before and after a compaction, and a session
# made before the pin, or a re-pin, keeps its own.


async def test_a_pinned_manual_renders_whole_in_every_request_through_a_compaction(
    tmp_path: Path,
) -> None:
    loop, playbooks = pinned(tmp_path)
    version = await playbooks.publish(loop.owner, manual())
    await playbooks.pin(loop.owner, ASSISTANT.name, version.name)
    session_id = await started(loop)
    await asked(loop, session_id, "What is the total?", reply(use("lookup")), reply(said("12.")))
    compact = History(session_id).control(ControlCommand.COMPACT)
    await loop.managers.steps.append_inputs(loop.owner, session_id, [compact])
    await asked(
        loop,
        session_id,
        "And the tax?",
        reply(said("Asked for the total; it is 12."), model="claude-haiku-4-5"),
        reply(use("lookup")),
        reply(said("1.2.")),
    )

    steps = await loop.history(session_id)
    assert [step.type for step in steps].count(StepType.SUMMARY) == 1, "compacted once"
    (switched,) = [step for step in steps if step.type is StepType.SWITCHED]
    first = min(step.seq for step in steps if step.type is StepType.MESSAGE)
    assert switched.seq < first, "pinned before anything arrives"
    calls = main_calls(loop)
    assert len(calls) == 4, "two requests before the compaction, two after"
    for call in calls:
        assert system(call) == [ASSISTANT.prompts[0], standing(version), DATA_NOTICE], (
            "after the kind's prompts, whole, never an excerpt"
        )
        turns = [b.text for m in call.messages for b in m.blocks if isinstance(b, TextBlock)]
        assert not any(STEPS[:60] in text for text in turns), "never in a turn"
    assert len({prefix(call) for call in calls}) == 1, "one cached prefix, byte for byte"


async def test_a_session_keeps_the_manual_it_was_made_with_through_a_re_pin_and_an_unpin(
    tmp_path: Path,
) -> None:
    loop, playbooks = pinned(tmp_path)
    before = await started(loop)
    first = await playbooks.publish(loop.owner, manual())
    await playbooks.pin(loop.owner, ASSISTANT.name, first.name)
    on_first = await started(loop)
    revised = STEPS.replace("Quote the ledger's line", "Cite the ledger's page")
    second = await playbooks.publish(loop.owner, manual(body=revised))
    assert (await playbooks.pins(loop.owner))[0].version == 1, "a publish moves no pin"
    await playbooks.pin(loop.owner, ASSISTANT.name, second.name)
    on_second = await started(loop)
    await playbooks.unpin(loop.owner, ASSISTANT.name)
    after = await started(loop)

    for session_id, expected in (
        (before, None),
        (on_first, first),
        (on_second, second),
        (after, None),
        (on_first, first),
    ):
        (call,) = await asked(loop, session_id, "What is the total?", reply(said("12.")))
        held = [text for text in system(call) if text.startswith(STANDING_LEAD)]
        assert held == ([] if expected is None else [standing(expected)]), session_id


async def test_a_retried_start_pins_once_and_keeps_the_version_it_recorded(
    tmp_path: Path,
) -> None:
    loop, playbooks = pinned(tmp_path)
    first = await playbooks.publish(loop.owner, manual())
    await playbooks.pin(loop.owner, ASSISTANT.name, first.name)
    session_id = await started(loop)
    await playbooks.publish(loop.owner, manual(body="1. Answer from the ledger."))
    await playbooks.pin(loop.owner, ASSISTANT.name, first.name)
    assert await started(loop, session_id) == session_id
    steps = await loop.history(session_id)
    (switched,) = [step for step in steps if step.type is StepType.SWITCHED]
    assert switched.as_text() == skill_md(first)
    (invocation,) = await loop.storage.get_playbook_storage().read_invocations(
        loop.owner.org_id, session_id, 10
    )
    assert (invocation.version, invocation.pinned) == (1, True)


async def test_a_project_pin_wins_over_the_tenants_and_a_sub_agent_takes_its_kinds(
    tmp_path: Path,
) -> None:
    loop, playbooks = pinned(tmp_path)
    tenants = await playbooks.publish(loop.owner, manual())
    projects = await playbooks.publish(
        loop.owner,
        manual(body="1. Answer from the project's ledger.").model_copy(
            update={"name": "project-manual"}
        ),
    )
    pinned_project = await loop.managers.projects.create_project(loop.owner, make_project())
    other_project = await loop.managers.projects.create_project(
        loop.owner, make_project("octo/other")
    )
    await playbooks.pin(loop.owner, ASSISTANT.name, tenants.name)
    await playbooks.pin(loop.owner, ASSISTANT.name, projects.name, pinned_project.id)

    async def in_project(project_id: UUID) -> UUID:
        start = Start(id=new_id(), kind=ASSISTANT.name, title="the ledger")
        session = await loop.managers.projects.start_session(loop.owner, project_id, start)
        return session.id

    for project_id, expected in ((pinned_project.id, projects), (other_project.id, tenants)):
        root = await in_project(project_id)
        loop.anthropic.add(reply(said("A sub-agent will find it.")))
        await loop.loops.run(loop.owner, root)
        asked_for = Spawn(id=new_id(), kind=ASSISTANT.name, title="a part", objective="Sum it.")
        child = await loop.managers.agents.spawn(loop.owner, root, asked_for)
        for session_id in (root, child.id):
            steps = await loop.history(session_id)
            (switched,) = [step for step in steps if step.type is StepType.SWITCHED]
            assert switched.as_text() == skill_md(expected), (project_id, session_id)


# Check 3: a manual's gates narrow the session's policy and never widen it.


async def test_a_manuals_gates_narrow_the_policy_and_never_widen_it(tmp_path: Path) -> None:
    # The platform's ceiling denies `note`; the manual asks only for a
    # person's approval of it, and denies `lookup`, which policy allows.
    ceilings = PolicyLayer(rules=(PolicyRule(tool="note", decision=Decision.DENY),))
    loop, playbooks = pinned(tmp_path, ceilings)
    unpinned = await started(loop)
    gates = (
        PlaybookGate(tool="lookup", decision=Decision.DENY),
        PlaybookGate(tool="note", decision=Decision.APPROVE),
    )
    version = await playbooks.publish(loop.owner, manual(*gates))
    await playbooks.pin(loop.owner, ASSISTANT.name, version.name)
    session_id = await started(loop)
    assert await playbooks.gates_of(loop.owner, session_id) == gates
    assert await playbooks.gates_of(loop.owner, unpinned) == ()

    await asked(
        loop,
        session_id,
        "Look up the total, and note it.",
        reply(use("lookup"), use("note")),
        reply(said("I may do neither.")),
    )
    failures = [
        step.header.failure
        for step in await loop.history(session_id)
        if step.type is StepType.TOOL_RESPONSE and isinstance(step.header, ToolResponseHeader)
    ]
    assert failures == [ToolFailure.DENIED, ToolFailure.DENIED], "never held for approval"
    assert loop.tools["lookup"].ran_as == [] and loop.tools["note"].ran_as == []

    # The session made before the pin holds no gate of it.
    await asked(loop, unpinned, "What is the total?", reply(use("lookup")), reply(said("12.")))
    assert loop.tools["lookup"].ran_as == [loop.owner.user_id]


async def test_only_a_person_who_manages_the_tenant_pins_a_brief_a_session_holds_whole(
    tmp_path: Path,
) -> None:
    loop, playbooks = pinned(tmp_path)
    version = await playbooks.publish(loop.owner, manual())
    member = context(Role.MEMBER)
    member = member.model_copy(update={"org_id": loop.owner.org_id})
    with pytest.raises(NotAuthorized):
        await playbooks.pin(member, ASSISTANT.name, version.name)
    # The owner's place, as an agent's call runs under it: internal, never
    # in person.
    agents_call = build_context(
        RequestContext(request_id=new_id(), app=loop.owner.app),
        user_id=loop.owner.user_id,
        org_id=loop.owner.org_id,
        role=Role.OWNER,
        permissions=permissions_of(Role.OWNER),
        credential_kind=CredentialKind.INTERNAL,
    )
    with pytest.raises(NotAuthorized):
        await playbooks.pin(agents_call, ASSISTANT.name, version.name)
    with pytest.raises(UnknownAgentKind):
        await playbooks.pin(loop.owner, "no-such-kind", version.name)
    with pytest.raises(NotFound):
        await playbooks.pin(loop.owner, ASSISTANT.name, version.name, new_id())
    with pytest.raises(NotFound):
        await playbooks.pin(loop.owner, ASSISTANT.name, "no-such-playbook")
    long = await playbooks.publish(loop.owner, manual(body="x" * MAX_STANDING))
    with pytest.raises(ValidationFailed):
        await playbooks.pin(loop.owner, ASSISTANT.name, long.name)
    assert await playbooks.pins(loop.owner) == ()
    with pytest.raises(NotFound):
        await playbooks.unpin(loop.owner, ASSISTANT.name)


async def test_invoking_the_manuals_version_sends_no_second_brief(tmp_path: Path) -> None:
    loop, playbooks = pinned(tmp_path)
    version = await playbooks.publish(loop.owner, manual())
    await playbooks.pin(loop.owner, ASSISTANT.name, version.name)
    session_id = await started(loop)
    invocation = await playbooks.invoke(loop.owner, session_id, version.name)
    assert invocation.pinned
    assert not [s for s in await loop.history(session_id) if s.type is StepType.MESSAGE]
