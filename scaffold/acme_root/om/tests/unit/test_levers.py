"""Levers, as the platform reads them: each check finds its defect in a
agent playbook and none in a plain one, nor in quoted words, an agent playbook's
gates, or a thing not to stop; a publish with a finding lands and keeps
it with the version; and a reading of recorded sessions names the lever
that came before the stalls, by its kind, id, and version alone, with the
sessions behind it, counts an entry an agent read by its slug, and never
names one every session reached."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.intake import Wired, wired
from contracts.loops import reply, said, use

from acme.om.agent_knowledge.types.agent_knowledge import AgentKnowledgeStatus
from acme.om.agent_playbooks.impl.manager import AgentPlaybooksManagerImpl, AgentPlaybooksOptions
from acme.om.agent_playbooks.rules import skill_md
from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookDraft,
    AgentPlaybookGate,
)
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
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
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
    LeverCheck.UNKNOWN_NAME: PLAIN + "\nThen run the `run_tests` tool before you answer.",
    LeverCheck.UNBOUNDED_RETRY: PLAIN + "\nKeep retrying the lookup until it answers.",
    LeverCheck.PAST_SESSION_BOUND: PLAIN + "\n" + " ".join(f"r{n}" for n in range(3_000)),
}


def agent_playbook(body: str, *gates: AgentPlaybookGate) -> AgentPlaybook:
    return AgentPlaybook(
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


def test_a_plain_agent_playbook_has_no_finding() -> None:
    gated = agent_playbook(PLAIN, AgentPlaybookGate(tool="call_api", decision=Decision.DENY))
    assert checked(skill_md(gated), REACH, bound=BOUND, tools=("call_api",)) == ()


@pytest.mark.parametrize("defect", list(DEFECTS))
def test_each_check_finds_its_defect_and_only_it(defect: LeverCheck) -> None:
    found = checked(skill_md(agent_playbook(DEFECTS[defect])), REACH, bound=BOUND)
    assert [finding.check for finding in found] == [defect]
    assert all(len(finding.detail) <= 500 for finding in found)


def test_a_gate_on_a_tool_no_kind_holds_is_a_finding() -> None:
    gated = agent_playbook(PLAIN, AgentPlaybookGate(tool="deploy", decision=Decision.DENY))
    (found,) = checked(skill_md(gated), REACH, bound=BOUND, tools=("deploy",))
    assert (found.check, found.excerpt) == (LeverCheck.UNKNOWN_NAME, "deploy")


def test_a_reach_of_no_kind_judges_no_name() -> None:
    gated = agent_playbook(DEFECTS[LeverCheck.UNKNOWN_NAME])
    assert checked(skill_md(gated), LeverReach(), bound=BOUND, tools=("deploy",)) == ()


QUOTED = """## Steps

1. Set `DATABASE_URL` and `max_retries` before the migration.
2. Run the migration, and read its total with the `lookup` tool.

## Forbidden

Do not stop the database during the migration.
"""
"""An agent playbook a person writes: an environment variable and a configuration
key in backticks, and a thing not to stop."""

GATED = ("deploy", "publish", "push", "merge", "tag", "rollback")
"""Six tools, each gated for a person's approval."""


def publisher(platform: Wired) -> AgentPlaybooksManagerImpl:
    """The platform's agent playbooks, against kinds that hold the six tools."""
    managers, storage = platform.managers, platform.storage
    return AgentPlaybooksManagerImpl(
        storage.get_agent_playbook_storage(),
        managers.agent_sessions,
        storage.get_agent_session_storage(),
        managers.agents,
        managers.tenancy,
        managers.outbox,
        AgentPlaybooksOptions(session_bound=BOUND),
        REACH.model_copy(update={"tools": REACH.tools | set(GATED)}),
        managers.kinds,
        SessionProjectsBoundImpl(storage.get_project_storage()),
    )


async def test_quoted_words_six_gates_and_a_thing_not_to_stop_are_no_findings(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    gates = tuple(AgentPlaybookGate(tool=tool, decision=Decision.APPROVE) for tool in GATED)
    draft = AgentPlaybookDraft(
        name="migrate-the-records", description="Migrate the records.", body=QUOTED, gates=gates
    )
    published = await publisher(platform).publish(author, draft)
    assert published.findings == ()
    # Not to stop at all is still an instruction with no stopping condition.
    for told in ("Do not stop until the deploy is green.", "Never give up."):
        (found,) = checked(told, REACH)
        assert found.check is LeverCheck.UNBOUNDED_RETRY


async def test_the_checks_read_the_persons_words_and_the_size_the_whole_brief(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    gates = tuple(AgentPlaybookGate(tool=tool, decision=Decision.APPROVE) for tool in GATED)
    body = (PLAIN + "\n" + " ".join(f"r{n}" for n in range(2_000)))[: BOUND - 100]
    draft = AgentPlaybookDraft(
        name="long-brief", description="A long brief.", body=body, gates=gates
    )
    published = await publisher(platform).publish(author, draft)
    # The person's words fit; the brief a session receives, with its
    # frontmatter and its gates, does not.
    brief = len(skill_md(published))
    assert len(f"{draft.description}\n\n{body}") <= BOUND < brief
    assert published.findings is not None
    (found,) = published.findings
    assert found.check is LeverCheck.PAST_SESSION_BOUND
    assert found.detail.startswith(f"{brief} characters")


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
    draft = AgentPlaybookDraft(
        name="flaky-deploys",
        description="Deploy the service.",
        body=DEFECTS[LeverCheck.UNBOUNDED_RETRY],
    )
    published = await platform.agent_playbooks.publish(author, draft)
    assert published.version == 1
    assert [f.check for f in published.findings or ()] == [LeverCheck.UNBOUNDED_RETRY]
    assert (await platform.agent_playbooks.get_agent_playbook(author, "flaky-deploys")) == published
    plain = await platform.agent_playbooks.publish(author, draft.model_copy(update={"body": PLAIN}))
    assert (plain.version, plain.findings) == (2, ())


async def test_agent_knowledge_carries_its_findings_from_its_writing_to_its_review(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    written = await platform.agent_knowledge.write(
        author, "Deploys", ("deploy",), "Keep retrying the deploy until it is green."
    )
    assert [f.check for f in written.findings or ()] == [LeverCheck.UNBOUNDED_RETRY]
    edited = await platform.agent_knowledge.edit(
        author, written.id, "Deploys", ("deploy",), "Deploys go through the pipeline.", 1
    )
    assert edited.findings == ()
    session_id = await platform.start()
    suggested = await platform.agent_knowledge.suggest(
        await platform.agents_call(platform.owner),
        session_id,
        "Vendors",
        ("vendor",),
        "You must call the vendor first. Never call the vendor.",
    )
    kept = await platform.agent_knowledge.review(author, suggested.id, keep=True)
    assert kept.status is AgentKnowledgeStatus.REVIEWED
    assert [f.check for f in kept.findings or ()] == [LeverCheck.CONTRADICTION]


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
    flaky, house = [
        await platform.agent_playbooks.publish(
            author, AgentPlaybookDraft(name=name, description="A brief.", body=body)
        )
        for name, body in (("flaky-deploys", DEFECTS[LeverCheck.UNBOUNDED_RETRY]), ("house", PLAIN))
    ]
    note = await platform.agent_knowledge.write(
        author, "Totals", ("totals",), "Totals are monthly."
    )
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
            await platform.agent_playbooks.invoke(platform.owner, session_id, name)
        if at in (0, 2, 4):
            await platform.agent_knowledge.recall(platform.owner, session_id, "the totals")
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
    assert first.lever == LeverRef(kind=LeverKind.AGENT_PLAYBOOK, id=flaky.id, version=1)
    assert set(first.spun_sessions) == {sessions[0], sessions[1]}
    assert (first.spun, first.sessions, first.spun_without, first.sessions_without) == (2, 2, 1, 3)
    assert second.lever == LeverRef(
        kind=LeverKind.AGENT_KNOWLEDGE, id=note.id, version=note.version
    )
    assert set(second.spun_sessions) == {sessions[0], sessions[2]}
    assert house.id not in {standing.lever.id for standing in reading.standings}
    # An operator who reads sees a lever's shape, never the tenant's words.
    assert all(set(s.lever.model_dump()) == {"kind", "id", "version"} for s in reading.standings)
    answered = reading.model_dump_json()
    assert note.slug and note.slug not in answered and "flaky-deploys" not in answered


async def test_an_entry_an_agent_reads_by_its_slug_is_reached_and_counted(
    platform: Wired,
) -> None:
    author = platform.person(Role.MEMBER)
    note = await platform.agent_knowledge.write(
        author, "Totals", ("totals",), "Totals are monthly."
    )
    assert note.slug is not None
    since = platform.clock.now - timedelta(minutes=1)
    sessions = [await platform.start() for _ in range(3)]
    await platform.agent_playbooks.publish(
        author, AgentPlaybookDraft(name="house", description="A brief.", body=PLAIN)
    )
    # Every session is woken by the same agent playbook, which ranks nowhere.
    for session_id in sessions:
        await platform.agent_playbooks.invoke(platform.owner, session_id, "house")
    agent = await platform.agents_call(platform.owner)
    # What `read_agent_knowledge` does: the entry by its slug, and a read again.
    for _ in range(2):
        assert (await platform.agent_knowledge.read(agent, sessions[0], note.slug)).id == note.id
    await spin(platform, sessions[0])
    for session_id in sessions[1:]:
        await answer(platform, session_id)

    reading = await build_levers(platform.storage).read_levers(
        operator(), platform.owner.org_id, since, utcnow() + timedelta(minutes=1)
    )
    (standing,) = reading.standings
    assert standing.lever == LeverRef(
        kind=LeverKind.AGENT_KNOWLEDGE, id=note.id, version=note.version
    )
    assert (standing.sessions, standing.spun, standing.spun_sessions) == (1, 1, (sessions[0],))


async def test_a_reading_is_an_operators_over_a_window_that_ends_after_it_starts(
    platform: Wired,
) -> None:
    await platform.agent_playbooks.publish(
        platform.person(), AgentPlaybookDraft(name="house", description="A brief.", body=PLAIN)
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
        await platform.agent_playbooks.invoke(platform.owner, session_id, "house")
        await answer(platform, session_id)
    bounded = await levers.read_levers(operator(), platform.owner.org_id, since, now)
    assert (bounded.sessions, bounded.complete) == (1, False)


def test_a_lever_present_everywhere_or_no_more_often_with_a_stall_ranks_nowhere() -> None:
    everywhere = LeverRef(kind=LeverKind.AGENT_PLAYBOOK, id=new_id(), version=1)
    even = LeverRef(kind=LeverKind.AGENT_PLAYBOOK, id=new_id(), version=1)
    stalled = SpinTally(inconclusive=1)
    sessions = [
        SessionLevers(session_id=new_id(), spin=stalled, levers=(everywhere, even)),
        SessionLevers(session_id=new_id(), spin=SpinTally(), levers=(everywhere, even)),
        SessionLevers(session_id=new_id(), spin=stalled, levers=(everywhere,)),
        SessionLevers(session_id=new_id(), spin=SpinTally(), levers=(everywhere,)),
    ]
    assert standings(sessions, 20) == ()
