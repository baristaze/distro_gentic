"""The agents a platform ships, over memory: each kind is a profile over the
one loop; the platform assistant holds no workspace, repository, or shell
tool, and a call to one is refused; it drafts configuration and a
person applies it; its corpus is what the knowledge map lists for the
tenant's users and nothing else; and a validation session is platform
work on the queue, run on a fresh executor with no model call."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from contracts.loops import reply, said
from contracts.platform_agents import CORPUS, Later, Platform, calls, platform_over
from contracts.project_storage import in_project, make_binding

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.integrations.model_providers.calls import ModelCall, ModelReply
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.kind import AgentKind, DoneRule
from acme.om.agents.types.result import Claim
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    Permission,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.record import RunPurpose
from acme.om.evidence.types.validation import Delivery
from acme.om.exceptions import NotAuthorized, NotFound, PreconditionFailed, UnsafeConfiguration
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.catalog import (
    PlatformAgents,
    read_corpus,
    refuse_reach,
    with_shipped,
)
from acme.om.platform_agents.kinds import (
    ANALYSIS_KIND,
    ENGINEER_KIND,
    PLATFORM_ASSISTANT_KIND,
    SHIPPED,
)
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.root import build_managers
from acme.om.steps.types.content import TextBlock, ToolResultBlock
from acme.om.steps.types.header import LoopOutcome, ToolFailure
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, PolicyRule, ToolPolicy
from acme.om.tools.types.tool import ToolClass
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

ROOT = Path(__file__).resolve().parents[3]
"""The root of this project, where its knowledge map is."""

WORKER = AppContext(type=AppType.WORKER, version="worker@test")
APP = AppContext(type=AppType.PORTAL, version="portal@test")


def unbound() -> object:
    raise AssertionError("no manager is reached while the catalog is read")


def shipped_catalog() -> tuple[ToolInterface, ...]:
    return with_shipped(
        PlatformAgents(corpus=CORPUS),
        (),
        (),
        sessions=unbound,  # pyright: ignore[reportArgumentType]
        policies=unbound,  # pyright: ignore[reportArgumentType]
        agents=unbound,  # pyright: ignore[reportArgumentType]
        evidence=unbound,  # pyright: ignore[reportArgumentType]
        workspaces=unbound,  # pyright: ignore[reportArgumentType]
        intake=unbound,  # pyright: ignore[reportArgumentType]
    )


def classes_of(catalog: tuple[ToolInterface, ...]) -> dict[str, str]:
    return {tool.spec.name: tool.spec.authorization_class for tool in catalog}


def member_of(platform: Platform, *only: Permission) -> TenantContext:
    """Another person of the owner's tenant: a member, or one holding only
    the permissions named."""
    return build_context(
        RequestContext(request_id=new_id(), app=WORKER),
        user_id=new_id(),
        org_id=platform.owner.org_id,
        role=Role.MEMBER,
        permissions=only or permissions_of(Role.MEMBER),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


def a_policy(platform: Platform, *policy_rules: PolicyRule, version: int) -> ToolPolicy:
    now = utcnow()
    return ToolPolicy(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=platform.owner.user_id,
        updated_by=platform.owner.user_id,
        rules=policy_rules,
        version=version,
    )


def items_of(platform: Platform) -> list[WorkItem]:
    work = platform.storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    return [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]


# Every shipped agent is a profile over the one loop.


def test_every_shipped_agent_is_a_profile_that_sets_its_powers() -> None:
    classes = classes_of(shipped_catalog())
    names = [kind.name for kind in SHIPPED]
    assert names == ["engineer", "analysis", "planner", "platform_assistant"]
    for kind in SHIPPED:
        assert set(kind.tools) <= set(classes), f"{kind.name} names a tool the catalog lacks"
        assert kind.prompts, f"{kind.name} carries its prompts"
    delivering = {kind.name for kind in SHIPPED if kind.done_rule is DoneRule.RESULT_TOOL}
    assert delivering == {"engineer"}, "only the engineer changes a work product"
    assert kinds.VALIDATE in ENGINEER_KIND.tools
    assert ENGINEER_KIND.isolation.mode is IsolationMode.CONTAINER
    assert {classes[tool] for tool in ENGINEER_KIND.tools} >= {"write", "execute"}


# Each shipped kind reaches an accepted end; the engineer's success only on
# a passing validation at its head.

TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))
"""The workspace this suite prepares, in place of a container."""


def on_the_twin(kind: AgentKind) -> AgentKind:
    """The shipped profile, whole, in the workspace this suite can prepare."""
    return kind.model_copy(update={"version": kind.version + 1, "isolation": TWIN})


def all_fail(check: str, trial: int) -> str:
    return "failed"


def citing(claim: Claim) -> Later:
    """The engineer's turn that submits `claim`, citing the runs the last
    validation it read answered."""

    def turn(call: ModelCall) -> ModelReply:
        runs: list[str] = []
        for message in call.messages:
            for block in message.blocks:
                if isinstance(block, ToolResultBlock):
                    for part in block.parts:
                        if isinstance(part, TextBlock) and '"runs"' in part.text:
                            runs = json.loads(part.text)["runs"]
        return reply(
            calls(kinds.SUBMIT_RESULT, f"use_{claim.value}", claim=claim.value, evidence=runs)
        )

    return turn


@pytest.fixture
def evidenced(tmp_path: Path) -> tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl]:
    executor = ScriptedExecutor(capabilities=frozenset())
    work = WorkProductMemoryImpl()
    platform = platform_over(
        tmp_path,
        kinds=(on_the_twin(ENGINEER_KIND), on_the_twin(ANALYSIS_KIND)),
        executor=executor,
        work_product=work,
    )
    return platform, executor, work


async def an_engineer(platform: Platform, work: WorkProductMemoryImpl, project_id: UUID) -> UUID:
    """An engineer session of the project, whose work product changed `src/`
    and is committed, and whose policy requires its unit check there."""
    session_id = await platform.start(kinds.ENGINEER)
    binding = make_binding(session_id, project_id)
    await platform.storage.get_project_storage().bind_session(platform.owner.org_id, binding)
    delivery = Delivery(project="reports", base="b1", head="c2", changed=("src/report.py",))
    work.deliver(platform.owner.org_id, session_id, delivery)
    await platform.say(session_id, "The weekly report misses its total. Fix it.")
    return session_id


async def test_the_engineers_success_needs_a_passing_validation_at_its_head(
    evidenced: tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl],
) -> None:
    platform, executor, work = evidenced
    projects = platform.storage.get_project_storage()
    project_id = await in_project(projects, platform.owner.org_id)
    policy = make_policy(policy_key(project_id))
    await platform.managers.evidence.write_policy(platform.owner, policy)

    # No validation at its head, then a failing one: no success counts, and
    # a failure explained by the runs is an accepted end.
    executor.outcome = all_fail
    failing = await an_engineer(platform, work, project_id)
    platform.anthropic.add(
        reply(calls(kinds.SUBMIT_RESULT, "use_bare", claim="succeeded", evidence=[])),
        reply(calls(kinds.VALIDATE, "use_validate")),
        citing(Claim.SUCCEEDED),
        citing(Claim.FAILED),
    )
    run = await platform.managers.loop.run(platform.owner, failing)
    assert run.outcome is LoopOutcome.FAILED
    failure, text = await platform.answer(failing, "use_bare")
    assert failure is ToolFailure.DENIED and "cites its evidence" in text
    failure, text = await platform.answer(failing, "use_succeeded")
    assert failure is ToolFailure.DENIED and "did not pass" in text

    # A passing validation at its head: the success is accepted, verified.
    executor.outcome = lambda check, trial: "passed"
    passing = await an_engineer(platform, work, project_id)
    platform.anthropic.add(reply(calls(kinds.VALIDATE, "use_validate")), citing(Claim.SUCCEEDED))
    run = await platform.managers.loop.run(platform.owner, passing)
    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(passing, "use_succeeded")
    assert failure is None and "verified" in text and "unverified" not in text
    assert [request.version for request in executor.requests] == ["c2", "c2"]


async def test_analysis_the_planner_and_the_assistant_end_by_their_answer(
    evidenced: tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl],
) -> None:
    platform, _, _ = evidenced
    for kind, answer in (
        (kinds.ANALYSIS, "Finding: the total is dropped when a week has no rows (report.log)."),
        (kinds.PLANNER, "Plan: one task, a new engineer session for the dropped total."),
        (kinds.PLATFORM_ASSISTANT, "A session waits while its tenant is at its share."),
    ):
        session_id = await platform.start(kind)
        await platform.say(session_id, "Go on.")
        platform.anthropic.add(reply(said(answer)))
        run = await platform.managers.loop.run(platform.owner, session_id)
        assert run.outcome is LoopOutcome.SUCCEEDED, kind
        steps = await platform.history(session_id)
        assert answer in [step.as_text() for step in steps], kind


# Check 1: the assistant holds no workspace, repository, shell, or domain
# tool, and a call to one is refused.


def test_the_assistant_only_reads_and_hands_on_and_has_no_workspace() -> None:
    classes = classes_of(shipped_catalog())
    assistant = PLATFORM_ASSISTANT_KIND
    assert {classes[tool] for tool in assistant.tools} == {ToolClass.READ, ToolClass.SPAWN}
    assert assistant.isolation.mode is IsolationMode.NONE
    assert assistant.authority is AuthorityMode.DELEGATED
    workspace = {kinds.LIST_FILES, kinds.READ_FILE, kinds.WRITE_FILE, kinds.RUN_COMMAND}
    assert not workspace & set(assistant.tools)
    assert rules.reach_refusal(assistant, classes) is None


@pytest.mark.parametrize(
    ("tool", "authorization_class"),
    [
        ("run_command", ToolClass.EXECUTE),  # a shell
        ("write_file", ToolClass.WRITE),  # a workspace
        ("open_pull_request", ToolClass.INTEGRATION),  # a repository
        ("ship_order", "shipping"),  # a product's domain class
        ("apply_tool_policy", ToolClass.CONFIGURATION),
        ("bind_secret", ToolClass.CREDENTIALS),
    ],
)
def test_an_assistant_that_reaches_further_is_refused(tool: str, authorization_class: str) -> None:
    reaching = PLATFORM_ASSISTANT_KIND.model_copy(
        update={"version": 2, "tools": (*PLATFORM_ASSISTANT_KIND.tools, tool)}
    )
    classes = {**classes_of(shipped_catalog()), tool: authorization_class}
    refusal = rules.reach_refusal(reaching, classes)
    assert refusal is not None and tool in refusal


def test_an_assistant_with_a_workspace_or_steady_authority_is_refused_at_boot(
    tmp_path: Path,
) -> None:
    classes = classes_of(shipped_catalog())
    with_workspace = PLATFORM_ASSISTANT_KIND.model_copy(
        update={"version": 2, "isolation": ENGINEER_KIND.isolation}
    )
    steady = PLATFORM_ASSISTANT_KIND.model_copy(
        update={"version": 2, "authority": AuthorityMode.STEADY}
    )
    assert rules.reach_refusal(with_workspace, classes) is not None
    assert rules.reach_refusal(steady, classes) is not None
    # The root refuses it whole: a version an adopter declares meets the
    # check the platform's own does.
    with pytest.raises(UnsafeConfiguration):
        build_managers(
            StorageMemoryImpl(),
            InfraLocalImpl(tmp_path),
            agent_kinds=(with_workspace,),
            platform_agents=PlatformAgents(corpus=CORPUS),
        )


def test_a_catalog_with_two_tools_of_one_name_is_refused() -> None:
    catalog = shipped_catalog()
    with pytest.raises(UnsafeConfiguration):
        refuse_reach(SHIPPED, (*catalog, catalog[0]))


async def test_a_call_from_the_assistant_to_a_workspace_or_a_shell_is_refused(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "Run the tests for me.")
    platform.anthropic.add(
        reply(
            said("Let me try."),
            calls(kinds.RUN_COMMAND, "use_shell", argv=["make", "test"]),
            calls(kinds.WRITE_FILE, "use_write", path="notes.txt", text="x"),
            calls(kinds.READ_FILE, "use_read", path="README.md"),
        ),
        reply(said("I cannot run commands or touch files; an engineer can.")),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    for use_id, tool in (
        ("use_shell", kinds.RUN_COMMAND),
        ("use_write", kinds.WRITE_FILE),
        ("use_read", kinds.READ_FILE),
    ):
        failure, text = await platform.answer(session_id, use_id)
        assert failure is ToolFailure.INVALID_INPUT
        assert f"there is no tool named {tool!r}" in text
    # The catalog holds every one of them: an engineer's session has them.
    engineer_id = await platform.start(kinds.ENGINEER)
    engineer = await platform.managers.agent_sessions.get_session(platform.owner, engineer_id)
    assert {kinds.RUN_COMMAND, kinds.WRITE_FILE, kinds.READ_FILE} <= set(engineer.tools)


async def test_the_assistant_hands_engineering_on_and_reads_where_it_stands(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "The weekly report sometimes misses its total. Fix it.")
    objective = (
        "The weekly report sometimes misses its total. Reproduce it, fix it, and show the "
        "total is there on every run."
    )
    platform.anthropic.add(
        reply(
            said("This is engineering work."),
            calls(kinds.HAND_OFF, "use_hand", title="The missing total", objective=objective),
        ),
        reply(said("An engineer session holds it; confirm it to start.")),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(session_id, "use_hand")
    assert failure is None
    engineer_id = UUID(json.loads(text)["session_id"])
    engineer = await platform.managers.agent_sessions.get_session(platform.owner, engineer_id)
    # A session of its own, which names where it came from and waits for its
    # person: the assistant's conversation is not in it, only the objective.
    assert (engineer.kind, engineer.handed_off_from) == (kinds.ENGINEER, session_id)
    assert engineer.status is SessionStatus.IDLE
    handed = await platform.history(engineer_id)
    assert [step.as_text() for step in handed] == [objective]

    await platform.say(session_id, "Where does it stand?")
    platform.anthropic.add(
        reply(calls(kinds.READ_SESSION, "use_read", session_id=str(engineer_id))),
        reply(said("It waits for you to confirm it.")),
    )
    await platform.managers.loop.run(platform.owner, session_id)
    failure, text = await platform.answer(session_id, "use_read")
    assert failure is None
    state = json.loads(text)
    assert (state["kind"], state["status"]) == (kinds.ENGINEER, "idle")


# Check 2: the assistant cannot apply configuration; a person does.


async def test_the_assistant_drafts_the_policy_and_a_person_applies_it(tmp_path: Path) -> None:
    platform = platform_over(tmp_path)
    policies = platform.managers.tools
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "Let my engineers run commands unattended.")
    platform.anthropic.add(
        reply(
            said("Here is a draft."),
            calls(
                kinds.DRAFT_TOOL_POLICY,
                "use_draft",
                rules=[{"authorization_class": "execute", "decision": "allow"}],
            ),
            calls(
                kinds.DRAFT_TOOL_POLICY,
                "use_bad",
                rules=[{"tool": "rm_rf", "decision": "allow"}],
            ),
        ),
        reply(said("The draft adds one rule. Apply it when you are ready.")),
    )

    await platform.managers.loop.run(platform.owner, session_id)

    failure, text = await platform.answer(session_id, "use_draft")
    flat = text.replace(" ", "")
    assert failure is None
    assert '"valid":true' in flat and '"based_on":1' in flat and '"added":[{' in flat
    failure, text = await platform.answer(session_id, "use_bad")
    assert failure is None and "rm_rf" in text and '"valid":false' in text.replace(" ", "")
    # The draft wrote nothing: what is live is as it was.
    assert (await policies.get_policy(platform.owner)).rules == ()
    # No tool of the assistant changes configuration.
    classes = classes_of(shipped_catalog())
    assert ToolClass.CONFIGURATION not in {classes[t] for t in PLATFORM_ASSISTANT_KIND.tools}

    # A person who manages the tenant applies it; one who does not cannot.
    rule = PolicyRule(authorization_class=ToolClass.EXECUTE, decision=Decision.ALLOW)
    with pytest.raises(NotAuthorized):
        await policies.write_policy(member_of(platform), a_policy(platform, rule, version=1))
    applied = await policies.write_policy(platform.owner, a_policy(platform, rule, version=1))
    assert (await policies.get_policy(platform.owner)).rules == applied.rules == (rule,)


def test_a_draft_names_what_it_adds_and_removes_and_what_cannot_hold() -> None:
    keep = PolicyRule(authorization_class=ToolClass.READ, decision=Decision.ALLOW)
    drop = PolicyRule(authorization_class=ToolClass.WRITE, decision=Decision.APPROVE)
    add = PolicyRule(tool=kinds.RUN_COMMAND, decision=Decision.DENY)
    now = utcnow()
    live = ToolPolicy(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        rules=(keep, drop),
        version=3,
    )
    tools = frozenset({kinds.RUN_COMMAND})
    known = frozenset(c.value for c in ToolClass)

    draft = rules.draft_policy(live, (keep, add), (), tools, known)
    assert draft.valid and draft.based_on == 3
    assert (draft.added, draft.removed) == ((add,), (drop,))

    unknown = PolicyRule(
        tool="no_such_tool", authorization_class="telepathy", decision=Decision.ALLOW
    )
    bad = rules.draft_policy(live, (unknown,), (), tools, known)
    assert not bad.valid and len(bad.problems) == 2


# Check 3: the corpus holds only what the knowledge map lists for the
# tenant's users.


def a_knowledge_map(root: Path) -> None:
    """A guide listed for every audience, an internal document beside it
    listed only for the platform's own people, an unlisted one, and two
    lines that point off the repository."""
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "guide.md").write_text("# Guide\n\nA session waits in its lane.\n")
    (root / "docs" / "internal.md").write_text(
        "# Internal\n\nRotate the signing secret through the operator vault.\n"
    )
    (root / "docs" / "unlisted.md").write_text("# Unlisted\n\nThe signing secret rotates.\n")
    (root / "llms.txt").write_text(
        "# Acme\n\n"
        "## Platform developers\n\n"
        "- [Guide](docs/guide.md): the guide\n"
        "- [Internal](docs/internal.md): rotating secrets\n\n"
        "## Platform operators\n\n"
        "- [Internal](docs/internal.md): rotating secrets\n\n"
        "## Tenant users and admins\n\n"
        "- [Guide](docs/guide.md): the guide\n"
        "- [Outside](../outside.md): out of the folder\n"
        "- [A site](https://example.test/page.md): not a document here\n"
    )


async def test_the_corpus_holds_only_what_the_map_lists_for_the_tenants_users(
    tmp_path: Path,
) -> None:
    a_knowledge_map(tmp_path / "repo")
    corpus = read_corpus(tmp_path / "repo")

    assert [document.path for document in corpus.documents] == ["docs/guide.md"]
    # The internal document, in the same folder as a listed one, is not
    # there, so a search for its words finds nothing.
    assert rules.search(corpus, "rotate the signing secret", 5) == ()
    found = rules.search(corpus, "why does a session wait", 5)
    assert [(p.path, p.heading) for p in found] == [("docs/guide.md", "Guide")]

    # The assistant's search answers from that corpus and no other.
    platform = platform_over(tmp_path, corpus=corpus)
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "How do I rotate the signing secret?")
    platform.anthropic.add(
        reply(said("Let me look."), calls(kinds.SEARCH_CORPUS, "use_search", query="signing")),
        reply(said("The documentation does not say.")),
    )
    await platform.managers.loop.run(platform.owner, session_id)
    failure, text = await platform.answer(session_id, "use_search")
    assert failure is None and text.replace(" ", "") == '{"passages":[]}'


def test_the_copys_corpus_is_its_maps_tenant_section_and_no_internal_document() -> None:
    corpus = read_corpus(ROOT)
    listed = rules.listed((ROOT / "llms.txt").read_text(), rules.TENANT_USERS)
    paths = [document.path for document in corpus.documents]
    assert paths == [entry.path for entry in listed] and "om/README.md" in paths
    for internal in ("ops/README.md", "docs/runbooks/support.md", "specs/architecture.md"):
        assert internal not in paths, f"{internal} is listed for the platform's own people"


def test_a_map_line_off_the_repository_is_never_a_document() -> None:
    assert not rules.local_path("../outside.md")
    assert not rules.local_path("/etc/passwd")
    assert not rules.local_path("https://example.test/page.md")
    assert not rules.local_path("docs/guide.md#a-heading")
    assert rules.local_path("docs/guide.md")


def test_a_listed_link_that_leads_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (tmp_path / "secret.md").write_text("# Secret\n\nThe operator vault's address.\n")
    (root / "docs" / "guide.md").symlink_to(tmp_path / "secret.md")
    (root / "llms.txt").write_text("## Tenant users and admins\n\n- [Guide](docs/guide.md): it\n")
    with pytest.raises(ValueError, match="resolves outside"):
        read_corpus(root)


# Check 2: a validation session is platform work on the queue, run on a
# fresh executor with no model call.

HEAD = "c" * 40
BASE = "b" * 40


async def test_a_validation_session_is_platform_work_that_finishes_with_its_record(
    tmp_path: Path,
) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    platform = platform_over(tmp_path, executor=executor)
    # The claim hands work only of a tenant that is there.
    platform.owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", "ajax", "ann@ajax.test", "Ann"
    )
    project_id = new_id()
    policy = make_policy(policy_key(project_id))
    await platform.managers.evidence.write_policy(platform.owner, policy)
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=project_id, check_name="unit", head=HEAD, base=BASE
    )

    session = await validations.start_validation(platform.owner, start)

    assert await validations.start_validation(platform.owner, start) == session
    assert session.status is ValidationStatus.QUEUED
    assert [(i.kind, i.lane, i.target_id) for i in items_of(platform)] == [
        (WorkKind.VALIDATION, "default", session.id)
    ], "one item on the platform's own lane, and no loop"
    # The platform's worker claims it, as it claims any of its own work, and
    # the check runs on the executor.
    claimed = await platform.managers.work.claim(
        RequestContext(request_id=new_id(), app=WORKER),
        "default",
        (WorkKind.VALIDATION,),
        "maintenance-1",
        timedelta(seconds=30),
    )
    assert claimed is not None
    ctx, item = claimed
    finished = await validations.run_validation(ctx, item.target_id)
    await platform.managers.work.complete(ctx, item)

    (asked,) = executor.requests
    assert (asked.session_id, asked.version, asked.source) == (session.id, HEAD, BASE)
    assert ([c.name for c in asked.checks], asked.protected) == (["unit"], policy.protected)
    (validation,) = await platform.managers.evidence.get_validations(ctx, session.id, 10)
    (record,) = (await platform.managers.evidence.get_runs(ctx, session.id, None, 10)).items
    assert (finished.status, finished.run_id) == (ValidationStatus.FINISHED, record.id)
    assert validation.records == (record.id,)
    assert (record.executor, record.version, record.purpose) == (
        executor.name,
        HEAD,
        RunPurpose.VALIDATION,
    ), "the same execution record an agent's validation writes"
    assert [(i.kind, i.status) for i in items_of(platform)] == [
        (WorkKind.VALIDATION, WorkStatus.DONE)
    ]
    assert platform.model_calls() == 0, "no model was called"
    # It runs its check once: run again, it runs nothing; finished with
    # another run, it is refused.
    assert await validations.run_validation(ctx, session.id) == finished
    assert len(executor.requests) == 1
    with pytest.raises(PreconditionFailed):
        await validations.finish_validation(ctx, session.id, new_id())


async def test_a_validation_session_whose_run_was_kept_finishes_without_running_again(
    tmp_path: Path,
) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    platform = platform_over(tmp_path, executor=executor)
    project_id = new_id()
    await platform.managers.evidence.write_policy(
        platform.owner, make_policy(policy_key(project_id))
    )
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=project_id, check_name="unit", head=HEAD, base=BASE
    )
    session = await validations.start_validation(platform.owner, start)
    # A worker that kept the run and died before it finished the session.
    kept = await platform.managers.evidence.run_check(
        platform.owner, session.id, project_id, "unit", HEAD, BASE
    )

    finished = await validations.run_validation(platform.owner, session.id)

    assert finished.run_id == kept.records[0]
    assert len(executor.requests) == 1, "the retry ran nothing"
    with pytest.raises(PreconditionFailed, match="declares no check"):
        await platform.managers.evidence.run_check(
            platform.owner, new_id(), project_id, "lint", HEAD, BASE
        )


async def test_a_validation_session_is_its_tenants_and_a_reader_starts_none(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=new_id(), check_name="smoke", head=HEAD, base=BASE
    )
    session = await validations.start_validation(platform.owner, start)

    other = platform_over(tmp_path / "other", storage=platform.storage)
    with pytest.raises(NotFound):
        await other.managers.platform_agents.get_validation(other.owner, session.id)
    with pytest.raises(NotAuthorized):
        await validations.start_validation(
            member_of(platform, Permission.READ), start.model_copy(update={"id": new_id()})
        )
