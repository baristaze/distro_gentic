"""Levers, as the platform reads them: each check finds its defect in a
playbook and none in a plain one; a publish with a finding lands and keeps
it with the version; and a reading of recorded sessions names the lever
that came before the stalls, with the sessions behind it, and never one
every session reached."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.intake import Wired, wired
from contracts.loops import reply, said, use

from acme.om.agents.types.kind import AgentKindCatalog
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorPermission,
    OperatorRole,
    Role,
)
from acme.om.exceptions import NotAuthorized, ValidationFailed
from acme.om.knowledge.types.knowledge import KnowledgeStatus
from acme.om.levers.impl.manager import LeversOptions
from acme.om.levers.root import build_levers
from acme.om.levers.rules import (
    REPEAT_FLOOR,
    checked,
    reach_of,
    spin_of,
    standings,
)
from acme.om.levers.types.lever import (
    LeverCheck,
    LeverKind,
    LeverReach,
    LeverRef,
    SessionLevers,
    SpinTally,
)
from acme.om.playbooks.rules import skill_md
from acme.om.playbooks.types.playbook import (
    Playbook,
    PlaybookDraft,
    PlaybookGate,
)
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.tools.types.policy import Decision
from acme.om.trust.types.shape import shape_of

REACH = LeverReach(tools=frozenset({"lookup", "call_api"}), kinds=frozenset({"steady"}))
BOUND = 8_000

PLAIN = """## Steps

1. Look the total up with the `lookup` tool.
2. Say it, with the record it came from.
3. Ask a `steady` agent to file it when the person agrees.

## Safety

Never write to a record. Retry a failed lookup at most twice, then say what failed.
"""

DEFECTS = {
    LeverCheck.REPEATED_PHRASE: PLAIN
    + "\n".join("The source of truth decides." for _ in range(REPEAT_FLOOR + 1)),
    LeverCheck.CONTRADICTION: PLAIN + "\nYou must call the vendor first.\nNever call the vendor.",
    LeverCheck.UNKNOWN_NAME: PLAIN + "\nThen run `run_tests` before you answer.",
    LeverCheck.UNBOUNDED_RETRY: PLAIN + "\nKeep retrying the lookup until it answers.",
    LeverCheck.PAST_SESSION_BOUND: PLAIN + "\n" + " ".join(f"r{n}" for n in range(3_000)),
}


def playbook(body: str, *gates: PlaybookGate) -> Playbook:
    return Playbook(
        id=new_id(),
        created_at=utcnow(),
        name="answer-a-question",
        version=1,
        description="Answer a question from the records.",
        body=body,
        gates=gates,
        published_by=new_id(),
    )


def operator() -> OperatorContext:
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.READ),
    )


@pytest.fixture
def platform(tmp_path: Path) -> Wired:
    return wired(tmp_path)


def test_a_plain_playbook_has_no_finding() -> None:
    gated = playbook(PLAIN, PlaybookGate(tool="call_api", decision=Decision.DENY))
    assert checked(skill_md(gated), REACH, bound=BOUND, tools=("call_api",)) == ()


@pytest.mark.parametrize("defect", list(DEFECTS))
def test_each_check_finds_its_defect_and_only_it(defect: LeverCheck) -> None:
    found = checked(skill_md(playbook(DEFECTS[defect])), REACH, bound=BOUND)
    assert [finding.check for finding in found] == [defect]
    assert all(len(finding.detail) <= 500 for finding in found)


def test_a_gate_on_a_tool_no_kind_holds_is_a_finding() -> None:
    gated = playbook(PLAIN, PlaybookGate(tool="deploy", decision=Decision.DENY))
    (found,) = checked(skill_md(gated), REACH, bound=BOUND, tools=("deploy",))
    assert (found.check, found.excerpt) == (LeverCheck.UNKNOWN_NAME, "deploy")


def test_a_retry_with_its_stopping_condition_and_a_kind_by_name_are_no_findings() -> None:
    body = PLAIN + "\nKeep retrying the lookup, at most three times.\nStart a `steady` agent."
    assert checked(body, REACH) == ()
    (found,) = checked(PLAIN + "\nStart a `reviewer` agent.", REACH)
    assert (found.check, found.excerpt) == (LeverCheck.UNKNOWN_NAME, "reviewer")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "`" * 50_000,
        "must " * 10_000,
        "keep trying " * 4_000,
        "\x00\ud800 never never never",
        "a b c " * 8_000,
    ],
)
def test_any_text_is_read_and_answered_never_a_crash(text: str) -> None:
    for finding in checked(text, REACH, bound=BOUND):
        assert len(finding.detail) <= 500
        assert finding.excerpt is None or len(finding.excerpt) <= 500


def test_a_lever_reaches_the_latest_version_of_every_kind(platform: Wired) -> None:
    reach = reach_of(platform.managers.kinds)
    assert "steady" in reach.kinds and "lookup" in reach.tools
    older = platform.managers.kinds.kinds[0]
    newer = older.model_copy(update={"version": older.version + 1, "tools": ("lookup",)})
    later = reach_of(AgentKindCatalog(kinds=(older, newer)))
    assert later.tools == frozenset({"lookup"})


async def test_a_publish_with_a_finding_lands_and_keeps_it_with_the_version(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    draft = PlaybookDraft(
        name="flaky-deploys",
        description="Deploy the service.",
        body=DEFECTS[LeverCheck.UNBOUNDED_RETRY],
    )
    published = await platform.playbooks.publish(author, draft)
    assert published.version == 1
    assert [f.check for f in published.findings] == [LeverCheck.UNBOUNDED_RETRY]
    assert (await platform.playbooks.get_playbook(author, "flaky-deploys")) == published
    plain = await platform.playbooks.publish(author, draft.model_copy(update={"body": PLAIN}))
    assert (plain.version, plain.findings) == (2, ())


async def test_knowledge_carries_its_findings_from_its_writing_to_its_review(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    written = await platform.knowledge.write(
        author, "Deploys", ("deploy",), "Keep retrying the deploy until it is green."
    )
    assert [f.check for f in written.findings] == [LeverCheck.UNBOUNDED_RETRY]
    edited = await platform.knowledge.edit(
        author, written.id, "Deploys", ("deploy",), "Deploys go through the pipeline.", 1
    )
    assert edited.findings == ()
    session_id = await platform.start()
    suggested = await platform.knowledge.suggest(
        await platform.agents_call(platform.owner),
        session_id,
        "Vendors",
        ("vendor",),
        "You must call the vendor first. Never call the vendor.",
    )
    kept = await platform.knowledge.review(author, suggested.id, keep=True)
    assert kept.status is KnowledgeStatus.REVIEWED
    assert [f.check for f in kept.findings] == [LeverCheck.CONTRADICTION]


async def spin(platform: Wired, session_id: UUID) -> None:
    """A session whose model makes the same call until the engine's bound
    on a run of identical calls ends its loop."""
    platform.anthropic.add(*(reply(use("lookup")) for _ in range(5)))
    run = await platform.loops.run(platform.owner, session_id)
    assert run.end is RunEnd.ENDED and platform.anthropic.remaining == 0


async def answer(platform: Wired, session_id: UUID) -> None:
    """A session whose model looks once and answers."""
    platform.anthropic.add(reply(use("lookup")), reply(said("The total is 4.")))
    run = await platform.loops.run(platform.owner, session_id)
    assert run.end is RunEnd.ENDED and platform.anthropic.remaining == 0


async def test_the_reading_names_the_lever_before_the_stalls_and_never_one_everywhere(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    for name, body in (("flaky-deploys", DEFECTS[LeverCheck.UNBOUNDED_RETRY]), ("house", PLAIN)):
        await platform.playbooks.publish(
            author, PlaybookDraft(name=name, description="A brief.", body=body)
        )
    note = await platform.knowledge.write(author, "Totals", ("totals",), "Totals are monthly.")
    since = platform.clock.now - timedelta(minutes=1)
    sessions = [await platform.start() for _ in range(5)]
    reached = {
        0: ("flaky-deploys", "house"),
        1: ("flaky-deploys", "house"),
        2: ("house",),
        3: ("house",),
        4: ("house",),
    }
    for at, session_id in enumerate(sessions):
        for name in reached[at]:
            await platform.playbooks.invoke(platform.owner, session_id, name)
        if at in (0, 2, 4):
            await platform.knowledge.recall(platform.owner, session_id, "the totals")
        if at in (0, 1, 2):
            await spin(platform, session_id)
        else:
            await answer(platform, session_id)
    shapes = [shape_of(step) for step in await platform.history(sessions[0])]
    assert spin_of(shapes).inconclusive == 1 and spin_of(shapes).repeated_calls == 1

    levers = build_levers(platform.storage)
    reading = await levers.read_levers(
        operator(), platform.owner.org_id, since, utcnow() + timedelta(minutes=1)
    )
    assert (reading.sessions, reading.spun, reading.complete) == (5, 3, True)
    first, second = reading.standings
    assert (first.lever.kind, first.lever.name, first.lever.version) == (
        LeverKind.PLAYBOOK,
        "flaky-deploys",
        1,
    )
    assert set(first.spun_sessions) == {sessions[0], sessions[1]}
    assert (first.spun, first.sessions, first.spun_without, first.sessions_without) == (2, 2, 1, 3)
    assert (second.lever.kind, second.lever.id, second.lever.version) == (
        LeverKind.KNOWLEDGE,
        note.id,
        note.version,
    )
    assert second.lever.name == note.slug
    assert set(second.spun_sessions) == {sessions[0], sessions[2]}
    assert "house" not in {standing.lever.name for standing in reading.standings}


async def test_a_reading_is_an_operators_over_a_window_that_ends_after_it_starts(
    platform: Wired,
) -> None:
    await platform.playbooks.publish(
        platform.person(), PlaybookDraft(name="house", description="A brief.", body=PLAIN)
    )
    levers = build_levers(platform.storage, options=LeversOptions(sessions=1))
    since, now = platform.clock.now - timedelta(minutes=1), utcnow() + timedelta(minutes=1)
    with pytest.raises(ValidationFailed):
        await levers.read_levers(operator(), platform.owner.org_id, now, since)
    reader = operator().model_copy(update={"permissions": frozenset[OperatorPermission]()})
    with pytest.raises(NotAuthorized):
        await levers.read_levers(reader, platform.owner.org_id, since, now)
    for _ in range(2):
        session_id = await platform.start()
        await platform.playbooks.invoke(platform.owner, session_id, "house")
        await answer(platform, session_id)
    bounded = await levers.read_levers(operator(), platform.owner.org_id, since, now)
    assert (bounded.sessions, bounded.complete) == (1, False)


def test_a_lever_present_everywhere_or_no_more_often_with_a_stall_ranks_nowhere() -> None:
    everywhere = LeverRef(kind=LeverKind.PLAYBOOK, id=new_id(), name="house", version=1)
    even = LeverRef(kind=LeverKind.PLAYBOOK, id=new_id(), name="even", version=1)
    stalled = SpinTally(inconclusive=1)
    sessions = [
        SessionLevers(session_id=new_id(), spin=stalled, levers=(everywhere, even)),
        SessionLevers(session_id=new_id(), spin=SpinTally(), levers=(everywhere, even)),
        SessionLevers(session_id=new_id(), spin=stalled, levers=(everywhere,)),
        SessionLevers(session_id=new_id(), spin=SpinTally(), levers=(everywhere,)),
    ]
    assert standings(sessions, 20) == ()
