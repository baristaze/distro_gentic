"""The agents a platform ships, over memory: each kind is a profile over the
one loop; the platform assistant holds no workspace, repository, or shell
tool, and a call to one is refused; it drafts configuration and a
person applies it; its corpus is what the knowledge map lists for the
tenant's users and nothing else; the software engineer's edit changes exactly the
one place it names, and a search of the code answers within its bound and
inside the workspace alone; and a validation session is platform work on
the queue, run on a fresh executor with no model call."""

import hashlib
import json
import re
from collections.abc import Collection
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from contracts.factories import make_org
from contracts.hosts_storage import make_credential, make_host
from contracts.loops import reply, said
from contracts.platform_agents import (
    CORPUS,
    Later,
    Platform,
    a_software_engineer,
    a_software_engineer_starts_two_sub_agents_and_wakes_on_each_report,
    calls,
    citing,
    on_the_twin,
    platform_over,
    sub_agents_over,
)
from contracts.project_storage import in_project
from contracts.tools import (
    HOST_SPEC,
    Tools,
    failure_of,
    put_call,
    registry_of,
    result_text,
    tools_over,
)

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerTwinImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.workspaces import (
    IsolationMode,
    Workspace,
)
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.integrations.events import ChangedFile, CheckRun, PullRequestRead
from acme.integrations.events.twin import IntegrationTwinImpl, twin_installation
from acme.integrations.model_providers.calls import ModelCall, ModelReply
from acme.om import base
from acme.om.agent_sessions.limits import Limits
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents.types.kind import (
    NO_WORKSPACE,
    AgentKind,
    AgentKindCatalog,
    DoneRule,
    TreeLimits,
)
from acme.om.agents.types.request import Spawn
from acme.om.agents.types.result import Claim
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind
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
from acme.om.exceptions import (
    NotAuthorized,
    NotFound,
    PreconditionFailed,
    UnsafeConfiguration,
    ValidationFailed,
)
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.hosts.types.pool import HostPool
from acme.om.intake.tools import FORGE
from acme.om.models.types.fill import MAIN, SUMMARIZER, ModelSize
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.catalog import (
    PlatformAgents,
    read_corpus,
    refuse_reach,
    with_shipped,
)
from acme.om.platform_agents.kinds import (
    ANALYSIS_KIND,
    ANALYSIS_SHARE,
    ANALYSIS_V3,
    OPS_ANALYST_KIND,
    PLANNER_KIND,
    PLATFORM_ASSISTANT_KIND,
    REVIEWER_KIND,
    REVIEWER_SHARE,
    SHIPPED,
    SOFTWARE_ENGINEER_KIND,
    SOFTWARE_ENGINEER_SHARE,
    SOFTWARE_ENGINEER_V6,
    SOFTWARE_ENGINEER_V7,
)
from acme.om.platform_agents.tools import (
    MAX_EDIT,
    MAX_MATCH_TEXT,
    MAX_VIEW,
    EditFileImpl,
    SearchCodeImpl,
)
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.root import ProductKinds, build_managers, engine_tools
from acme.om.steps.types.content import TextBlock, ToolResultBlock
from acme.om.steps.types.header import (
    LoopOutcome,
    ParkReason,
    ToolFailure,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Step
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.native.load_toolset import callable_tools
from acme.om.tools.native.spawn_sub_agent import SPAWN_SUB_AGENT
from acme.om.tools.native.wait_for_sub_agents import WAIT_FOR_SUB_AGENTS
from acme.om.tools.registry import ToolRegistry
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import Decision, PolicyRule, ToolPolicy
from acme.om.tools.types.tool import ToolClass, ToolInput
from acme.om.tools.types.toolset import Toolset
from acme.om.windows.rules import READ_ARTIFACT
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus

ROOT = Path(__file__).resolve().parents[3]
"""The root of this project, where its knowledge map is."""

WORKER = AppContext(type=AppType.WORKER, version="worker@test")
APP = AppContext(type=AppType.PORTAL, version="portal@test")


def unbound() -> object:
    raise AssertionError("no manager is reached while the catalog is read")


def shipped_catalog() -> tuple[ToolInterface, ...]:
    """The engine's tools and the platform's, as the root offers them."""
    engine = engine_tools(
        unbound,  # pyright: ignore[reportArgumentType]
        unbound,  # pyright: ignore[reportArgumentType]
        unbound,  # pyright: ignore[reportArgumentType]
        unbound,  # pyright: ignore[reportArgumentType]
        unbound,  # pyright: ignore[reportArgumentType]
    )
    return *engine, *with_shipped(
        PlatformAgents(corpus=CORPUS),
        (),
        (),
        sessions=unbound,  # pyright: ignore[reportArgumentType]
        steps=unbound,  # pyright: ignore[reportArgumentType]
        projects=unbound,  # pyright: ignore[reportArgumentType]
        work=unbound,  # pyright: ignore[reportArgumentType]
        hosts=unbound,  # pyright: ignore[reportArgumentType]
        exec_relay=unbound,  # pyright: ignore[reportArgumentType]
        agent_automations=unbound,  # pyright: ignore[reportArgumentType]
        policies=unbound,  # pyright: ignore[reportArgumentType]
        agents=unbound,  # pyright: ignore[reportArgumentType]
        evidence=unbound,  # pyright: ignore[reportArgumentType]
        workspaces=unbound,  # pyright: ignore[reportArgumentType]
        intake=unbound,  # pyright: ignore[reportArgumentType]
        agent_knowledge=unbound,  # pyright: ignore[reportArgumentType]
        integrations=unbound,  # pyright: ignore[reportArgumentType]
        budgets=unbound,  # pyright: ignore[reportArgumentType]
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
    names = [(kind.name, kind.version) for kind in SHIPPED]
    assert names == [
        ("software_engineer", 1),
        ("software_engineer", 2),
        ("software_engineer", 3),
        ("software_engineer", 4),
        ("software_engineer", 5),
        ("software_engineer", 6),
        ("software_engineer", 7),
        ("software_engineer", 8),
        ("analysis", 1),
        ("analysis", 2),
        ("analysis", 3),
        ("analysis", 4),
        ("planner", 1),
        ("platform_assistant", 1),
        ("platform_assistant", 2),
        ("reviewer", 1),
        ("ops_analyst", 1),
    ]
    for kind in SHIPPED:
        assert set(kind.tools) <= set(classes), f"{kind.name} names a tool the catalog lacks"
        assert kind.prompts, f"{kind.name} carries its prompts"
    delivering = {kind.name for kind in SHIPPED if kind.done_rule is DoneRule.RESULT_TOOL}
    assert delivering == {"software_engineer", "reviewer"}, (
        "the software engineer and the reviewer deliver"
    )
    # Only the software engineer changes a work product: the reviewer delivers a
    # review, and nothing it holds writes.
    assert {classes[tool] for tool in REVIEWER_KIND.tools} == {"read", "integration"}
    assert REVIEWER_KIND.result_tool == kinds.SUBMIT_REVIEW
    assert kinds.VALIDATE in SOFTWARE_ENGINEER_KIND.tools
    assert SOFTWARE_ENGINEER_KIND.isolation.mode is IsolationMode.CONTAINER
    assert {classes[tool] for tool in SOFTWARE_ENGINEER_KIND.tools} >= {"write", "execute"}
    # The software engineer edits by one place, searches the code, and uses the
    # agent knowledge base; analysis searches and reads, and changes nothing.
    assert {
        kinds.EDIT_FILE,
        kinds.SEARCH_CODE,
        kinds.SEARCH_AGENT_KNOWLEDGE,
        kinds.READ_AGENT_KNOWLEDGE,
        kinds.SUGGEST_AGENT_KNOWLEDGE,
    } <= set(SOFTWARE_ENGINEER_KIND.tools)
    assert {kinds.SEARCH_CODE, kinds.SEARCH_AGENT_KNOWLEDGE, kinds.READ_AGENT_KNOWLEDGE} <= set(
        ANALYSIS_KIND.tools
    )
    assert {classes[tool] for tool in ANALYSIS_KIND.tools} == {"read", "execute", "spawn"}


def test_every_kind_roots_the_engines_tree_and_the_software_engineer_and_analysis_start_sub_agents() -> (
    None
):
    """Every shipped kind, at every version, roots a tree three levels deep
    that holds ten sub-agents besides its root, never a tree of one. The
    software engineer and analysis name the engine's two tools, and their policy runs
    a spawn unattended; the planner and the assistant hand work on and start
    no sub-agent."""
    for kind in SHIPPED:
        assert (kind.tree.height, kind.tree.count) == (3, 10), (kind.name, kind.version)
    classes = classes_of(shipped_catalog())
    assert (classes[SPAWN_SUB_AGENT], classes[WAIT_FOR_SUB_AGENTS]) == ("spawn", "read")
    for kind in (SOFTWARE_ENGINEER_KIND, ANALYSIS_KIND):
        assert {SPAWN_SUB_AGENT, WAIT_FOR_SUB_AGENTS} <= set(kind.tools), kind.name
        decided = {rule.authorization_class: rule.decision for rule in kind.policy.rules}
        assert decided[ToolClass.SPAWN] is Decision.ALLOW, kind.name
    for kind in SHIPPED:
        if kind.name in (kinds.PLANNER, kinds.PLATFORM_ASSISTANT):
            assert SPAWN_SUB_AGENT not in kind.tools, kind.name


def test_the_sub_agent_layer_says_a_sub_agent_starts_from_the_default_branch() -> None:
    """A sub-agent's workspace is a fresh checkout of the default branch, so
    every kind that starts one is told its sub-agents lack its changes, and
    asks about the default branch or hands over what they need."""
    for kind in (SOFTWARE_ENGINEER_KIND, ANALYSIS_KIND):
        assert kinds.SUB_AGENTS in kind.prompts, kind.name
    assert "a fresh checkout of the default branch, without your changes" in kinds.SUB_AGENTS
    assert "hand it what it needs in its objective" in kinds.SUB_AGENTS


def test_the_software_engineers_layers_name_analysis_for_a_question_and_the_software_engineer_for_a_change() -> (
    None
):
    """A software engineer starts a question that only reads or checks as analysis,
    under analysis's share, and another software engineer only for work that changes
    code: its prompt layers name both kinds, since the spawn tool's input
    names none."""
    layers = " ".join(SOFTWARE_ENGINEER_KIND.prompts)
    assert f'kind "{kinds.ANALYSIS}" for a question that only reads or checks' in layers
    assert f'your own kind, "{kinds.SOFTWARE_ENGINEER}" (or leave kind out)' in layers
    assert "only for work that changes code" in layers
    assert ANALYSIS_KIND.share == ANALYSIS_SHARE


def test_the_software_engineer_takes_a_baseline_again_when_its_base_moves() -> None:
    """A success counts only when a baseline at its base ran before its head
    was validated, so a software engineer whose base moved takes one there."""
    layers = " ".join(SOFTWARE_ENGINEER_KIND.prompts)
    assert "Take a baseline with validate before you change anything" in layers
    assert "Take a baseline again whenever your base moves" in layers


@pytest.mark.parametrize(
    ("latest", "before"),
    [(SOFTWARE_ENGINEER_V7, SOFTWARE_ENGINEER_V6), (ANALYSIS_KIND, ANALYSIS_V3)],
    ids=["software_engineer", "analysis"],
)
def test_the_software_engineer_and_analysis_read_back_a_kept_result_in_a_version_of_their_own(
    latest: AgentKind, before: AgentKind
) -> None:
    """A result too large for the window, or one compaction elided, is read
    back with read_artifact. Each kind names it in a version of its own,
    which changes nothing else, and the version before it stays shipped
    for the sessions pinned to it."""
    assert READ_ARTIFACT in latest.tools and READ_ARTIFACT not in before.tools
    assert latest.version == before.version + 1
    same = {"version": before.version, "tools": before.tools, "toolsets": before.toolsets}
    assert latest.model_copy(update=same) == before
    assert latest in SHIPPED and before in SHIPPED
    assert READ_ARTIFACT in {tool.spec.name for tool in shipped_catalog()}


def test_analysis_waits_for_every_report_before_it_answers() -> None:
    """Analysis ends its session with a turn that calls no tool, so its
    prompt has it wait for every sub-agent's report before that turn."""
    assert ANALYSIS_KIND.done_rule is DoneRule.ANSWER
    layers = " ".join(ANALYSIS_KIND.prompts)
    assert "wait for every sub-agent's report with wait_for_sub_agents before you answer" in layers


def test_the_software_engineers_step_guard_is_sized_for_a_change_and_its_share_follows_it() -> None:
    """A software engineer a spawn or an agent automation starts parks for a person past the
    calls a change takes, never at the engine's default guard, and its share
    pays for its loops at that guard."""
    assert SOFTWARE_ENGINEER_KIND.limits.step_guard == kinds.SOFTWARE_ENGINEER_STEP_GUARD
    assert SOFTWARE_ENGINEER_KIND.limits.step_guard > Limits().step_guard
    assert SOFTWARE_ENGINEER_KIND.share == SOFTWARE_ENGINEER_SHARE
    assert SOFTWARE_ENGINEER_SHARE.cost_micros == (
        kinds.SOFTWARE_ENGINEER_LOOPS
        * SOFTWARE_ENGINEER_KIND.limits.step_guard
        * kinds.CACHED_CALL_MICROS
    )


def test_analysis_keeps_the_engines_step_guard_and_its_share_follows_it() -> None:
    """Analysis reads and answers, so it parks at the engine's guard, and its
    share pays for its loops at that guard."""
    assert ANALYSIS_KIND.limits == Limits()
    assert ANALYSIS_KIND.share == ANALYSIS_SHARE
    assert ANALYSIS_SHARE.cost_micros == (
        kinds.ANALYSIS_LOOPS * ANALYSIS_KIND.limits.step_guard * kinds.CACHED_CALL_MICROS
    )


# A spawn starts every shipped kind a sub-agent runs as, under its share.

LEAD = AgentKind(
    name="lead",
    version=1,
    tools=(kinds.SUBMIT_RESULT,),
    done_rule=DoneRule.RESULT_TOOL,
    result_tool=kinds.SUBMIT_RESULT,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=2, count=1),
    isolation=NO_WORKSPACE,
)
"""A product's kind that delegates: it can grant the software engineer its result
tool, and its tree has room for one child."""


def test_every_shipped_kind_a_spawn_can_start_names_a_share() -> None:
    """A spawn refuses a kind that names no share. The software engineer and analysis
    split their work into sub-agents of either kind, a product's kind may
    spawn the software engineer, and a lead spawns the reviewer on the pull request
    another kind opened, so each one's latest version names a share; the
    planner, the assistant, and the operator are started by a person and
    name none."""
    catalog = AgentKindCatalog(kinds=SHIPPED)
    latest = [catalog.latest(name) for name in dict.fromkeys(kind.name for kind in SHIPPED)]
    spawning = [kind for kind in latest if SPAWN_SUB_AGENT in kind.tools]
    assert [kind.name for kind in spawning] == [kinds.SOFTWARE_ENGINEER, kinds.ANALYSIS]
    spawned = [*spawning, REVIEWER_KIND]
    assert [kind.share for kind in spawned] == [
        SOFTWARE_ENGINEER_SHARE,
        ANALYSIS_SHARE,
        REVIEWER_SHARE,
    ]
    for kind in spawned:
        assert kind.share is not None and (kind.share.cost_micros or 0) > 0, kind.name
    assert all(kind.share is None for kind in latest if kind not in spawned)


async def test_a_products_kind_spawns_the_software_engineer_under_its_share(tmp_path: Path) -> None:
    platform = platform_over(tmp_path, kinds=(LEAD,))
    lead_id = await platform.start(LEAD.name)
    asked = Spawn(
        id=new_id(),
        kind=kinds.SOFTWARE_ENGINEER,
        title="the total",
        objective="Fix the report's total.",
    )

    child = await platform.managers.agents.spawn(platform.owner, lead_id, asked)

    assert (child.kind, child.kind_version) == (
        kinds.SOFTWARE_ENGINEER,
        SOFTWARE_ENGINEER_KIND.version,
    )
    page = await platform.managers.budgets.get_budgets(platform.owner, None, 50)
    own = BudgetScope(kind=BudgetScopeKind.SESSION, key=str(child.id))
    assert [budget.amount for budget in page.items if budget.scope == own] == [
        SOFTWARE_ENGINEER_SHARE
    ]


async def test_a_lead_spawns_the_reviewer_under_its_share(tmp_path: Path) -> None:
    """A lead that holds the reviewer's tools starts it as a sub-agent, on
    a pull request its objective names, under the reviewer's share."""
    lead = LEAD.model_copy(
        update={
            "name": "review_lead",
            "tools": (*REVIEWER_KIND.tools, kinds.SUBMIT_RESULT),
        }
    )
    platform = platform_over(tmp_path, kinds=(lead,))
    lead_id = await platform.start(lead.name)
    asked = Spawn(
        id=new_id(), kind=kinds.REVIEWER, title="the review", objective="Review acme/widgets#12."
    )

    child = await platform.managers.agents.spawn(platform.owner, lead_id, asked)

    assert (child.kind, child.kind_version) == (kinds.REVIEWER, REVIEWER_KIND.version)
    page = await platform.managers.budgets.get_budgets(platform.owner, None, 50)
    own = BudgetScope(kind=BudgetScopeKind.SESSION, key=str(child.id))
    assert [budget.amount for budget in page.items if budget.scope == own] == [REVIEWER_SHARE]


# Each shipped kind reaches an accepted end; the software engineer's success only on
# a passing validation at its head.


def all_fail(check: str, trial: int) -> str:
    return "failed"


@pytest.fixture
def evidenced(tmp_path: Path) -> tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl]:
    executor = ScriptedExecutor(capabilities=frozenset())
    work = WorkProductMemoryImpl()
    platform = platform_over(
        tmp_path,
        kinds=(on_the_twin(SOFTWARE_ENGINEER_KIND), on_the_twin(ANALYSIS_KIND)),
        executor=executor,
        work_product=work,
    )
    return platform, executor, work


async def test_the_software_engineers_success_needs_a_passing_validation_at_its_head(
    evidenced: tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl],
) -> None:
    platform, executor, work = evidenced
    projects = platform.storage.get_project_storage()
    project_id = await in_project(projects, platform.owner.org_id)
    policy = make_policy(policy_key(project_id))
    await platform.managers.evidence.write_policy(platform.owner, policy)

    # A baseline first, then no validation at its head, then a failing one:
    # no success counts, and a failure explained by the runs is an accepted end.
    executor.outcome = all_fail
    failing = await a_software_engineer(platform, work, project_id)
    platform.anthropic.add(
        reply(calls(kinds.VALIDATE, "use_baseline", baseline=True)),
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
    passing = await a_software_engineer(platform, work, project_id)
    platform.anthropic.add(
        reply(calls(kinds.VALIDATE, "use_baseline", baseline=True)),
        reply(calls(kinds.VALIDATE, "use_validate")),
        citing(Claim.SUCCEEDED),
    )
    run = await platform.managers.loop.run(platform.owner, passing)
    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(passing, "use_succeeded")
    assert failure is None and "verified" in text and "unverified" not in text
    assert [request.version for request in executor.requests] == ["b1", "c2"] * 2


async def test_analysis_the_planner_and_the_assistant_end_by_their_answer(
    evidenced: tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl],
) -> None:
    platform, _, _ = evidenced
    for kind, answer in (
        (kinds.ANALYSIS, "Finding: the total is dropped when a week has no rows (report.log)."),
        (kinds.PLANNER, "Plan: one task, a new software engineer session for the dropped total."),
        (kinds.PLATFORM_ASSISTANT, "A session waits while its tenant is at its share."),
    ):
        session_id = await platform.start(kind)
        await platform.say(session_id, "Go on.")
        platform.anthropic.add(reply(said(answer)))
        run = await platform.managers.loop.run(platform.owner, session_id)
        assert run.outcome is LoopOutcome.SUCCEEDED, kind
        steps = await platform.history(session_id)
        assert answer in [step.as_text() for step in steps], kind


RENDERED = {
    (
        kinds.SOFTWARE_ENGINEER,
        8,
    ): "e0ebd4337f44f2b666a9ac87c692694ab6e181d0827c3f8c6f89d3f90e61e77d",
    (kinds.ANALYSIS, 4): "c94610c01308fb29e151e946431dd622706a314ed7901ae2b8fcbc4f95c27a1c",
    (kinds.PLANNER, 1): "7bf2a8de67d5c61b4947347bcfed8b7b50120beff54125446686a11272a36fa6",
    (
        kinds.PLATFORM_ASSISTANT,
        2,
    ): "a5930ae480ca5158fb24ad3d0256175d338a8ea78bbc73fb3de7141c9058bb14",
    (kinds.REVIEWER, 1): "72365994c5f47eb73b8f0c65cc9483d80e5f12d4cd637b707911c8424aea4e08",
    (kinds.OPS_ANALYST, 1): "0d02f035193f1a56484fb2c0da2521a7cd910a044f5f116598e5b15efcfda800",
}
"""Each shipped kind at the version a session starts on, and the digest of
its request's first two layers: its system text and its tools. A kind
version pins those bytes, the prefix its sessions share in the cache, so a
change to either is a new version of the kind."""


def layers_of(call: ModelCall) -> str:
    """The digest of a request's system text and its tools."""
    layers = {
        "system": [block.text for block in call.system],
        "tools": [tool.model_dump(mode="json") for tool in call.tools],
    }
    return hashlib.sha256(json.dumps(layers, sort_keys=True).encode()).hexdigest()


async def test_each_shipped_kind_renders_its_versions_bytes_with_a_break_after_its_prompts(
    evidenced: tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl],
) -> None:
    platform, _, work = evidenced
    project_id = await in_project(platform.storage.get_project_storage(), platform.owner.org_id)
    for kind in (
        SOFTWARE_ENGINEER_KIND,
        ANALYSIS_KIND,
        PLANNER_KIND,
        PLATFORM_ASSISTANT_KIND,
        REVIEWER_KIND,
        OPS_ANALYST_KIND,
    ):
        before = len(platform.anthropic.calls)
        if kind is SOFTWARE_ENGINEER_KIND:
            session_id = await a_software_engineer(platform, work, project_id)
        else:
            session_id = await platform.start(kind.name)
            await platform.say(session_id, "Go on.")
        platform.anthropic.add(reply(said("Done.")))
        await platform.managers.loop.run(platform.owner, session_id)
        call = platform.anthropic.calls[before]
        assert layers_of(call) == RENDERED[(kind.name, kind.version)], kind.name
        prompts = [prompt for prompt in kind.prompts if prompt]
        assert [block.text for block in call.system[: len(prompts)]] == prompts, kind.name
        assert call.system_break == len(prompts), f"{kind.name} caches the end of its prompts"


NAMED_ONE_BY_ONE: dict[tuple[str, int], tuple[str, ...]] = {
    (kinds.SOFTWARE_ENGINEER, 1): (
        "list_files",
        "read_file",
        "write_file",
        "run_command",
        "validate",
        "open_pull_request",
        "submit_result",
    ),
    **{
        (kinds.SOFTWARE_ENGINEER, version): (
            "list_files",
            "read_file",
            "search_code",
            "edit_file",
            "write_file",
            "run_command",
            "search_agent_knowledge",
            "read_agent_knowledge",
            "suggest_agent_knowledge",
            "validate",
            "open_pull_request",
            "submit_result",
        )
        for version in (2, 3, 4)
    },
    **{
        (kinds.SOFTWARE_ENGINEER, version): (
            "list_files",
            "read_file",
            "search_code",
            "edit_file",
            "write_file",
            "run_command",
            "search_agent_knowledge",
            "read_agent_knowledge",
            "suggest_agent_knowledge",
            "spawn_sub_agent",
            "wait_for_sub_agents",
            "validate",
            "open_pull_request",
            "submit_result",
            *(("read_artifact",) if version >= 7 else ()),
        )
        for version in (5, 6, 7, 8)
    },
    (kinds.ANALYSIS, 1): ("list_files", "read_file", "run_command"),
    **{
        (kinds.ANALYSIS, version): (
            "list_files",
            "read_file",
            "search_code",
            "run_command",
            "search_agent_knowledge",
            "read_agent_knowledge",
            *(("spawn_sub_agent", "wait_for_sub_agents") if version >= 3 else ()),
            *(("read_artifact",) if version >= 4 else ()),
        )
        for version in (2, 3, 4)
    },
    (kinds.PLANNER, 1): ("read_session", "hand_off_to_software_engineer"),
    (kinds.PLATFORM_ASSISTANT, 1): (
        "search_corpus",
        "read_session",
        "draft_tool_policy",
        "hand_off_to_software_engineer",
    ),
    (kinds.PLATFORM_ASSISTANT, 2): (
        "search_corpus",
        "search_agent_knowledge",
        "read_agent_knowledge",
        "read_session",
        "list_sessions",
        "read_wait",
        "list_projects",
        "read_project",
        "list_agent_automations",
        "read_agent_automation",
        "draft_tool_policy",
        "hand_off_to_software_engineer",
    ),
    (kinds.REVIEWER, 1): (
        "read_pull_request",
        "read_pull_request_file",
        "note_finding",
        "submit_review",
        "comment",
        "search_agent_knowledge",
        "read_agent_knowledge",
        "read_artifact",
    ),
    (kinds.OPS_ANALYST, 1): (
        "read_session",
        "list_sessions",
        "read_wait",
        "list_projects",
        "read_project",
        "list_agent_automations",
        "read_agent_automation",
        "list_hosts",
        "read_spend",
        "search_agent_knowledge",
        "read_agent_knowledge",
        "read_artifact",
    ),
}
"""Each shipped kind's tools by name: as it named them one by one before it
was built from toolsets, and those of a kind built from them from its first
version."""


def tool_block(catalog: tuple[ToolInterface, ...], names: Collection[str]) -> str:
    """The tool definitions a registry of `names` renders, as the bytes a
    request carries them in."""
    registry = ToolRegistry(tool for tool in catalog if tool.spec.name in names)
    return json.dumps([tool.model_dump(mode="json") for tool in registry.render()])


def test_each_shipped_kind_built_from_toolsets_renders_the_tool_block_it_named_one_by_one() -> None:
    """A kind built from the platform's toolsets renders, at every version
    still shipped, the same tool definitions, byte for byte, as the tools
    it named one by one: its sessions' cached prefix holds, and its powers
    are the same. It defers nothing, so every tool is in its first request,
    and each toolset it names is the platform's."""
    catalog = shipped_catalog()
    assert {(kind.name, kind.version) for kind in SHIPPED} == set(NAMED_ONE_BY_ONE)
    for kind in SHIPPED:
        named = NAMED_ONE_BY_ONE[(kind.name, kind.version)]
        assert not kind.deferred and not kind.waiting, (kind.name, kind.version)
        assert set(kind.toolsets) <= set(kinds.TOOLSETS), (kind.name, kind.version)
        assert sorted(kind.tools) == sorted(named), (kind.name, kind.version)
        held = callable_tools(kind.tools, kind.waiting, ())
        assert tool_block(catalog, held) == tool_block(catalog, named), (kind.name, kind.version)


def a_product_kind(*toolsets: Toolset, name: str = "triage") -> AgentKind:
    return AgentKind(
        name=name,
        version=1,
        toolsets=toolsets,
        done_rule=DoneRule.ANSWER,
        authority=AuthorityMode.STEADY,
    )


def test_a_products_kinds_name_the_platforms_toolsets_and_its_own() -> None:
    """A product's kind is built from the platform's toolsets and the ones
    the product adds beside them. A product never changes one of the
    platform's, and a kind names only a toolset one of the two declares,
    at the version and with the tools declared."""
    own = Toolset(name="tickets", version=1, summary="Read tickets.", tools=("read_ticket",))
    kind = a_product_kind(kinds.FILES_TOOLSET, own)
    product = ProductKinds(agents=(kind,), toolsets=(own,))
    assert set(product.agents[0].tools) == {*kinds.FILES_TOOLSET.tools, "read_ticket"}
    taken = own.model_copy(update={"name": kinds.FILES_TOOLSET.name})
    with pytest.raises(ValueError, match="is the platform's"):
        ProductKinds(toolsets=(taken,))
    with pytest.raises(ValueError, match="declares a version of a toolset twice"):
        ProductKinds(toolsets=(own, own))
    with pytest.raises(ValueError, match="neither the platform nor the product declares"):
        ProductKinds(agents=(kind,))
    other = kinds.FILES_TOOLSET.model_copy(update={"tools": (kinds.READ_FILE,)})
    with pytest.raises(ValueError, match="neither the platform nor the product declares"):
        ProductKinds(agents=(a_product_kind(other),))


def test_each_kind_holds_its_workspace_warm_for_its_grace_within_the_cache_life() -> None:
    """The software engineer and analysis hold their workspace warm after a loop for
    the prompt cache's life, and no longer; a product's kind names its own
    grace, never past that life, and only for a kind of its own."""
    for kind in SHIPPED:
        assert timedelta(0) <= ProductKinds().warm_grace(kind.name) <= kinds.PROMPT_CACHE_LIFE
    assert set(kinds.GRACES) == {kinds.SOFTWARE_ENGINEER, kinds.ANALYSIS}
    brief = timedelta(minutes=1)
    product = ProductKinds(agents=(a_product_kind(),), graces={"triage": brief})
    assert product.warm_grace("triage") == brief
    assert product.warm_grace(kinds.SOFTWARE_ENGINEER) == kinds.GRACES[kinds.SOFTWARE_ENGINEER]
    assert ProductKinds().warm_grace("unknown") == kinds.WARM_GRACE
    with pytest.raises(ValueError, match="runs outside the prompt cache's life"):
        ProductKinds(agents=(a_product_kind(),), graces={"triage": timedelta(hours=1)})
    with pytest.raises(ValueError, match="no agent kind of the product's"):
        ProductKinds(graces={kinds.SOFTWARE_ENGINEER: brief})


async def test_the_software_engineer_starts_two_sub_agents_and_wakes_on_each_report(
    tmp_path: Path,
) -> None:
    await a_software_engineer_starts_two_sub_agents_and_wakes_on_each_report(
        *sub_agents_over(tmp_path)
    )


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
        update={"version": 3, "isolation": SOFTWARE_ENGINEER_KIND.isolation}
    )
    steady = PLATFORM_ASSISTANT_KIND.model_copy(
        update={"version": 3, "authority": AuthorityMode.STEADY}
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
        reply(said("I cannot run commands or touch files; a software engineer can.")),
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
    # The catalog holds every one of them: a software engineer's session has them.
    software_engineer_id = await platform.start(kinds.SOFTWARE_ENGINEER)
    software_engineer = await platform.managers.agent_sessions.get_session(
        platform.owner, software_engineer_id
    )
    assert {kinds.RUN_COMMAND, kinds.WRITE_FILE, kinds.READ_FILE} <= set(software_engineer.tools)


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
        reply(said("A software engineer session holds it; confirm it to start.")),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(session_id, "use_hand")
    assert failure is None
    software_engineer_id = UUID(json.loads(text)["session_id"])
    software_engineer = await platform.managers.agent_sessions.get_session(
        platform.owner, software_engineer_id
    )
    # A session of its own, which names where it came from and waits for its
    # person: the assistant's conversation is not in it, only the objective.
    assert (software_engineer.kind, software_engineer.handed_off_from) == (
        kinds.SOFTWARE_ENGINEER,
        session_id,
    )
    assert software_engineer.status is SessionStatus.IDLE
    handed = await platform.history(software_engineer_id)
    assert [step.as_text() for step in handed] == [objective]

    await platform.say(session_id, "Where does it stand?")
    platform.anthropic.add(
        reply(calls(kinds.READ_SESSION, "use_read", session_id=str(software_engineer_id))),
        reply(said("It waits for you to confirm it.")),
    )
    await platform.managers.loop.run(platform.owner, session_id)
    failure, text = await platform.answer(session_id, "use_read")
    assert failure is None
    state = json.loads(text)
    assert (state["kind"], state["status"]) == (kinds.SOFTWARE_ENGINEER, "idle")


# Check 2: the assistant cannot apply configuration; a person does.


async def test_the_assistant_drafts_the_policy_and_a_person_applies_it(tmp_path: Path) -> None:
    platform = platform_over(tmp_path)
    policies = platform.managers.tools
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "Let my software engineers run commands unattended.")
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
    # The portal's pages are there, so a reply can link one.
    assert "docs/portal-routes.md" in paths
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


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"name": "lint"}, "declares no check unit"),
        ({"capabilities": ("gpu",)}, "needs gpu, which the executor lacks"),
    ],
    ids=["dropped", "unoffered"],
)
async def test_a_check_that_cannot_run_refuses_its_session_with_the_reason(
    tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    platform = platform_over(tmp_path, executor=executor)
    # The run reads its starter's live context: the starter is a member.
    platform.owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", "ajax", "ann@ajax.test", "Ann"
    )
    project_id = new_id()
    evidence = platform.managers.evidence
    await evidence.write_policy(platform.owner, make_policy(policy_key(project_id)))
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=project_id, check_name="unit", head=HEAD, base=BASE
    )
    session = await validations.start_validation(platform.owner, start)
    # After the start, the policy drops the check, or asks of it what no
    # executor here offers.
    policy = await evidence.get_policy(platform.owner, policy_key(project_id))
    checks = tuple(each.model_copy(update=change) for each in policy.checks)
    await evidence.write_policy(
        platform.owner, policy.model_copy(update={"checks": checks, "requirements": ()})
    )

    with pytest.raises(PreconditionFailed, match=reason):
        await validations.run_validation(platform.owner, session.id)

    gone = await validations.get_validation(platform.owner, session.id)
    assert gone.status is ValidationStatus.REFUSED
    assert gone.refusal is not None and reason in gone.refusal
    assert (gone.run_id, gone.version, executor.requests) == (None, 2, [])
    # Asked again, it runs nothing and says the same; it never finishes.
    with pytest.raises(PreconditionFailed, match=reason):
        await validations.run_validation(platform.owner, session.id)
    with pytest.raises(PreconditionFailed, match="is refused"):
        await validations.finish_validation(platform.owner, session.id, new_id())
    assert await validations.get_validation(platform.owner, session.id) == gone
    assert executor.requests == []


async def test_a_validation_session_is_its_tenants_and_a_reader_starts_none(
    tmp_path: Path,
) -> None:
    platform = platform_over(tmp_path)
    project_id = new_id()
    await platform.managers.evidence.write_policy(
        platform.owner, make_policy(policy_key(project_id))
    )
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=project_id, check_name="unit", head=HEAD, base=BASE
    )
    session = await validations.start_validation(platform.owner, start)

    other = platform_over(tmp_path / "other", storage=platform.storage)
    with pytest.raises(NotFound):
        await other.managers.platform_agents.get_validation(other.owner, session.id)
    with pytest.raises(NotAuthorized):
        await validations.start_validation(
            member_of(platform, Permission.READ), start.model_copy(update={"id": new_id()})
        )
    # A project whose policy is another tenant's, or a check its policy does
    # not declare, is refused before anything is written.
    crossing = start.model_copy(update={"id": new_id()})
    with pytest.raises(NotFound, match="declares no validation policy"):
        await other.managers.platform_agents.start_validation(other.owner, crossing)
    undeclared = start.model_copy(update={"id": new_id(), "check_name": "lint"})
    with pytest.raises(ValidationFailed, match="declares no check lint"):
        await validations.start_validation(platform.owner, undeclared)
    for refused in (crossing, undeclared):
        with pytest.raises(NotFound):
            await validations.get_validation(platform.owner, refused.id)
    assert [i.target_id for i in items_of(platform)] == [session.id]


# The software engineer's edit and search, in a directory on this host, with real
# files and real processes.

SOURCE = (
    "def total(cart):\n"
    "    tax = 0\n"
    "    return sum(cart) + tax\n"
    "\n"
    "\n"
    "def count(cart):\n"
    "    tax = 0\n"
    "    return len(cart)\n"
)


def on_the_host(tmp_path: Path) -> Tools:
    transport = TransportLocalImpl(
        tmp_path / "records", SecretsLocalImpl(None, {}), BrokerTwinImpl()
    )
    return tools_over(transport, WorkspaceHostImpl(tmp_path / "workspaces"))


async def called(
    tools: Tools,
    tool: ToolInterface,
    ctx: TenantContext,
    workspace: Workspace,
    **call_input: object,
) -> Step:
    """The tool's call, run as the loop runs one the gate let through."""
    found = await put_call(
        tools.manager,
        tools.steps,
        ctx,
        tool.spec.name,
        dict(call_input),
        tool.spec.authorization_class,
    )
    return await tools.manager.execute(
        ctx,
        registry_of(tool),
        found.request,
        found.call_input,
        workspace,
        epoch=found.epoch,
        tree_deadline=None,
    )


async def test_an_edit_changes_exactly_the_place_it_names(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    cart = Path(workspace.location) / "cart.py"
    cart.write_text(SOURCE)
    edit = EditFileImpl(unbound)  # pyright: ignore[reportArgumentType]
    # One exact match: that place changes, and every other byte stays.
    response = await called(
        tools,
        edit,
        ctx,
        workspace,
        path="cart.py",
        old_text="sum(cart) + tax",
        new_text="sum(cart) + tax + 1",
    )
    assert failure_of(response) is None, result_text(response)
    assert cart.read_text() == SOURCE.replace("sum(cart) + tax", "sum(cart) + tax + 1")
    assert json.loads(result_text(response))["line"] == 3
    # A line range: those lines and no other, the last one's end kept.
    before = cart.read_text().splitlines(keepends=True)
    response = await called(
        tools,
        edit,
        ctx,
        workspace,
        path="cart.py",
        start_line=7,
        end_line=8,
        new_text="    return len(cart) or 0",
    )
    assert failure_of(response) is None, result_text(response)
    assert cart.read_text() == "".join([*before[:6], "    return len(cart) or 0\n"])
    assert json.loads(result_text(response)) | {"size": 0} == {
        "path": "cart.py",
        "line": 7,
        "lines": 1,
        "size": 0,
    }
    # A file whose lines end in CRLF keeps them.
    windows = Path(workspace.location) / "notes.txt"
    windows.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    response = await called(
        tools, edit, ctx, workspace, path="notes.txt", start_line=2, end_line=2, new_text="2"
    )
    assert failure_of(response) is None, result_text(response)
    assert windows.read_bytes() == b"one\r\n2\r\nthree\r\n"


async def test_an_edit_that_is_not_one_place_is_refused_and_changes_nothing(
    tmp_path: Path,
) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    root = Path(workspace.location)
    (root / "cart.py").write_text(SOURCE)
    (root / "aaa.txt").write_text("aaa\n")
    (root / "blob.bin").write_bytes(b"\xff\xfe tax = 0\n")
    (root / "big.txt").write_text("tax = 0\n" + "x" * MAX_EDIT)
    outside = tmp_path / "outside.py"
    outside.write_text(SOURCE)
    names = ("cart.py", "aaa.txt", "blob.bin", "big.txt")
    files = {path: path.read_bytes() for path in (*(root / name for name in names), outside)}
    edit = EditFileImpl(unbound)  # pyright: ignore[reportArgumentType]
    refused = (
        # Two places, then two overlapping ones: the edit lands on neither.
        ({"path": "cart.py", "old_text": "    tax = 0\n"}, "matches 2 places"),
        ({"path": "aaa.txt", "old_text": "aa"}, "matches 2 places"),
        ({"path": "cart.py", "old_text": "    tax = 1\n"}, "matches no place"),
        ({"path": "cart.py", "start_line": 8, "end_line": 9}, "has 8 lines"),
        # Not text, or past the bound: never written back cut or mangled.
        ({"path": "blob.bin", "old_text": "tax = 0"}, "not UTF-8 text"),
        ({"path": "big.txt", "old_text": "tax = 0"}, "past the"),
    )
    for change, why in refused:
        response = await called(tools, edit, ctx, workspace, new_text="tax = 2", **change)
        assert failure_of(response) is ToolFailure.PERMANENT, change
        assert why in result_text(response), result_text(response)
    # A call that names both places, or neither, or a range backwards, and a
    # path out of the workspace, is refused before anything is read.
    for change in (
        {"path": "cart.py", "old_text": "tax", "start_line": 2, "end_line": 2},
        {"path": "cart.py"},
        {"path": "cart.py", "start_line": 3, "end_line": 2},
        {"path": "cart.py", "start_line": 3},
        {"path": "../../outside.py", "old_text": "    return len(cart)\n"},
        {"path": str(outside), "old_text": "    return len(cart)\n"},
    ):
        response = await called(tools, edit, ctx, workspace, new_text="tax = 2", **change)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, change
    assert {path: path.read_bytes() for path in files} == files


async def test_a_search_of_the_code_answers_within_its_bound(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    root = Path(workspace.location)
    (root / "src").mkdir()
    for n in range(30):
        (root / "src" / f"m{n:02}.py").write_text(f"import os\nvalue = 'needle {n}'\n")
    (root / "src" / "long.py").write_text("needle " + "x" * 5_000 + "\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("needle\n")
    (root / "blob.bin").write_bytes(b"needle\x00\n")
    search = SearchCodeImpl()
    response = await called(tools, search, ctx, workspace, pattern="needle", limit=5)
    answer = json.loads(result_text(response))
    assert len(answer["matches"]) == 5 and answer["more"] is True
    response = await called(tools, search, ctx, workspace, pattern="needle", path="src", limit=100)
    answer = json.loads(result_text(response))
    assert answer["more"] is False and len(answer["matches"]) == 31
    paths = {match["path"] for match in answer["matches"]}
    assert all(path.startswith("src/") for path in paths), "never .git, never a binary file"
    assert max(len(match["text"]) for match in answer["matches"]) == MAX_MATCH_TEXT
    response = await called(tools, search, ctx, workspace, pattern="needle 1[0-9]'$")
    answer = json.loads(result_text(response))
    assert sorted((m["path"], m["line"]) for m in answer["matches"]) == [
        (f"src/m{n}.py", 2) for n in range(10, 20)
    ]
    # The bound holds on bytes too: a flood of long lines is read only to
    # the output's bound, and the answer still holds its limit.
    for n in range(300):
        (root / "src" / f"wide{n:03}.py").write_text(("needle " + "y" * 2_000 + "\n") * 3)
    response = await called(tools, search, ctx, workspace, pattern="needle y", limit=100)
    answer = json.loads(result_text(response))
    assert len(answer["matches"]) == 100 and answer["more"] is True
    assert len(result_text(response)) < 50_000, "within what the model reads of one output"
    # No match is an empty answer; a pattern grep cannot read is the model's.
    response = await called(tools, search, ctx, workspace, pattern="haystack")
    assert json.loads(result_text(response)) == {"matches": [], "more": False}
    response = await called(tools, search, ctx, workspace, pattern="needle (")
    assert failure_of(response) is ToolFailure.PERMANENT


async def test_a_search_of_the_code_reads_inside_the_workspace_alone(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "kept.py").write_text("needle inside\n")
    (tmp_path / "beside.txt").write_text("needle outside\n")
    search = SearchCodeImpl()
    for path in ("..", "../..", "../../beside.txt", "src/../..", "/", str(tmp_path), "a\x00b"):
        response = await called(tools, search, ctx, workspace, pattern="needle", path=path)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, path
    response = await called(tools, search, ctx, workspace, pattern="needle")
    answer = json.loads(result_text(response))
    assert [m["path"] for m in answer["matches"]] == ["kept.py"]


async def test_a_search_of_one_file_answers_its_matching_line(tmp_path: Path) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "src").mkdir()
    (Path(workspace.location) / "src" / "cart.py").write_text("import os\nvalue = 'needle'\n")
    search = SearchCodeImpl()
    response = await called(tools, search, ctx, workspace, pattern="needle", path="src/cart.py")
    assert json.loads(result_text(response)) == {
        "matches": [{"path": "src/cart.py", "line": 2, "text": "value = 'needle'"}],
        "more": False,
    }


class WatchedSearch(SearchCodeImpl):
    """The search, counting the times it runs."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> base.Platform:
        self.runs += 1
        return await super().run(ctx, call_input, runtime)


async def test_a_pattern_of_more_than_one_line_is_refused_before_it_runs(
    tmp_path: Path,
) -> None:
    ctx = context(Role.SERVICE, make_org())
    tools = on_the_host(tmp_path)
    workspace = await tools.manager.prepare_workspace(ctx, new_id(), HOST_SPEC)
    (Path(workspace.location) / "kept.py").write_text("needle\nhaystack\n")
    search = WatchedSearch()
    for pattern in ("needle\n", "needle\r", "\nneedle", "needle\r\nhay"):
        response = await called(tools, search, ctx, workspace, pattern=pattern)
        assert failure_of(response) is ToolFailure.INVALID_INPUT, pattern
    assert search.runs == 0
    response = await called(tools, search, ctx, workspace, pattern="needle")
    assert [m["text"] for m in json.loads(result_text(response))["matches"]] == ["needle"]
    assert search.runs == 1


# The reviewer and the ops analyst are templates as data: each is built from
# the platform's toolsets, asks sizes, and is versioned in the catalog.


def test_the_reviewer_and_the_ops_analyst_are_built_from_toolsets_and_ask_sizes() -> None:
    catalog = AgentKindCatalog(kinds=SHIPPED)
    assert catalog.latest(kinds.REVIEWER) == REVIEWER_KIND
    assert catalog.latest(kinds.OPS_ANALYST) == OPS_ANALYST_KIND
    assert REVIEWER_KIND.toolsets == (
        kinds.REVIEW_TOOLSET,
        kinds.AGENT_KNOWLEDGE_TOOLSET,
        kinds.ARTIFACTS_TOOLSET,
    )
    assert OPS_ANALYST_KIND.toolsets == (
        kinds.RECORDS_TOOLSET,
        kinds.OPERATIONS_TOOLSET,
        kinds.AGENT_KNOWLEDGE_TOOLSET,
        kinds.ARTIFACTS_TOOLSET,
    )
    for kind in (REVIEWER_KIND, OPS_ANALYST_KIND):
        assert set(kind.toolsets) <= set(kinds.TOOLSETS), kind.name
        held = {tool for toolset in kind.toolsets for tool in toolset.tools}
        # The reviewer names the forge's comment alone; the operator names
        # nothing alone.
        alone = {kinds.COMMENT} if kind is REVIEWER_KIND else set()
        assert set(kind.tools) == held | alone, kind.name
    asked = {kind.name: {ask.role: ask.size for ask in kind.asks} for kind in SHIPPED}
    assert asked[kinds.REVIEWER] == {MAIN: ModelSize.XL, SUMMARIZER: ModelSize.S}
    assert asked[kinds.OPS_ANALYST] == {MAIN: ModelSize.L, SUMMARIZER: ModelSize.S}
    # A product builds its own kinds from the same toolsets.
    lead = a_product_kind(kinds.SUB_AGENTS_TOOLSET, name="lead")
    assert ProductKinds(agents=(lead,)).agents == (lead,)


# The reviewer reads a recorded pull request through the forge, notes its
# findings with file and line, and delivers its review through its result
# tool; nothing it holds writes what it reviews.

REVIEWED = "acme/widgets#12"
REVIEWED_HEAD = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
CART = (
    "def total(cart):\n"
    "    prices = [item.price for item in cart]\n"
    "    return sum(prices) / len(prices)\n"
)
RECORDED = PullRequestRead(
    address=REVIEWED,
    url="https://forge.example/acme/widgets/pull/12",
    title="Average the cart",
    body="The total is the average price.",
    state="open",
    head=REVIEWED_HEAD,
    head_ref="sessions/average",
    base_ref="main",
    files=(
        ChangedFile(
            path="src/cart.py",
            status="modified",
            patch=(
                "@@ -1,2 +1,3 @@\n def total(cart):\n     prices = [item.price for item in cart]\n"
                "+    return sum(prices) / len(prices)"
            ),
        ),
    ),
    checks=(CheckRun(name="unit", status="completed", conclusion="failure"),),
    provenance="real",
)
"""A pull request as the forge answers a read of it."""


async def reviewing(tmp_path: Path) -> tuple[Platform, IntegrationTwinImpl]:
    """The platform over a forge that holds the recorded pull request, whose
    installation the owner's tenant connected."""
    forge = IntegrationTwinImpl(FORGE)
    forge.record_pull_request(RECORDED, {"src/cart.py": CART.encode()})
    platform = platform_over(tmp_path, forge=forge)
    await platform.connect(FORGE, twin_installation("acme"))
    return platform, forge


def submitting(claim: Claim) -> Later:
    """The reviewer's turn that submits its review, citing every id its
    reads and its findings answered."""

    def turn(call: ModelCall) -> ModelReply:
        cited: list[str] = []
        for message in call.messages:
            for block in message.blocks:
                if not isinstance(block, ToolResultBlock):
                    continue
                for part in block.parts:
                    if isinstance(part, TextBlock) and part.text.startswith("{"):
                        found = json.loads(part.text).get("id")
                        if found is not None:
                            cited.append(found)
        return reply(calls(kinds.SUBMIT_REVIEW, "use_review", claim=claim.value, evidence=cited))

    return turn


NAMED_ID = re.compile(r"submit_review cites: ([0-9a-f-]{36})")
"""The id a failed read of a review names, which a failed review cites."""


def giving_up(reason: str) -> Later:
    """The reviewer's turn that says why it could not review, and submits
    the review as failed, citing the id each failed read named."""

    def turn(call: ModelCall) -> ModelReply:
        cited = [
            found
            for message in call.messages
            for block in message.blocks
            if isinstance(block, ToolResultBlock)
            for part in block.parts
            if isinstance(part, TextBlock)
            for found in NAMED_ID.findall(part.text)
        ]
        return reply(
            said(reason),
            calls(kinds.SUBMIT_REVIEW, "use_review", claim=Claim.FAILED.value, evidence=cited),
        )

    return turn


async def test_a_reviewer_answers_its_findings_with_file_and_line_through_its_result_tool(
    tmp_path: Path,
) -> None:
    platform, forge = await reviewing(tmp_path)
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Review {REVIEWED}.")
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=REVIEWED)),
        reply(
            calls(
                kinds.READ_PULL_REQUEST_FILE,
                "use_file",
                on=REVIEWED,
                path="src/cart.py",
                head=REVIEWED_HEAD,
            ),
            calls(
                kinds.NOTE_FINDING,
                "use_finding",
                on=REVIEWED,
                path="src/cart.py",
                head=REVIEWED_HEAD,
                line=3,
                grade="high",
                text="An empty cart divides by zero, so its total raises.",
            ),
        ),
        submitting(Claim.SUCCEEDED),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    # It asks XL of its main role: the size's model reviews.
    assert platform.anthropic.calls[0].model == "claude-opus-5-5"
    failure, text = await platform.answer(session_id, "use_read")
    read = json.loads(text)
    assert failure is None
    assert (read["on"], read["head"]) == (REVIEWED, REVIEWED_HEAD)
    assert [(f["path"], f["patch"] is not None) for f in read["files"]] == [("src/cart.py", True)]
    assert read["checks"] == [{"name": "unit", "status": "completed", "conclusion": "failure"}]
    _, text = await platform.answer(session_id, "use_file")
    assert json.loads(text)["text"] == CART
    failure, text = await platform.answer(session_id, "use_finding")
    finding = json.loads(text)
    assert failure is None
    assert (finding["path"], finding["line"], finding["head"], finding["grade"]) == (
        "src/cart.py",
        3,
        REVIEWED_HEAD,
        "high",
    )
    # The review is accepted, verified: the gate read the read and the
    # finding it cites in the session's own history.
    failure, text = await platform.answer(session_id, "use_review")
    assert failure is None and "accepted, verified" in text
    assert UUID(finding["id"]) != UUID(read["id"])
    # The forge was read, and nothing was written to it.
    assert forge.posted == [] and forge.refs == {} and forge.pull_requests == []


async def test_a_finding_off_the_file_and_a_review_citing_no_read_are_refused(
    tmp_path: Path,
) -> None:
    platform, _ = await reviewing(tmp_path)
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Review {REVIEWED}.")
    at = {"on": REVIEWED, "head": REVIEWED_HEAD, "grade": "low", "text": "Name it."}
    platform.anthropic.add(
        reply(
            calls(kinds.NOTE_FINDING, "use_past", path="src/cart.py", line=40, **at),
            calls(kinds.NOTE_FINDING, "use_out", path="../secrets.txt", line=1, **at),
            calls(kinds.NOTE_FINDING, "use_kept", path="src/cart.py", line=1, **at),
        ),
        # A success that cites a finding and no read of the pull request.
        submitting(Claim.SUCCEEDED),
        reply(
            calls(
                kinds.SUBMIT_REVIEW,
                "use_made_up",
                claim="succeeded",
                evidence=[str(new_id())],
            )
        ),
        reply(said("I could not review it.")),
    )

    await platform.managers.loop.run(platform.owner, session_id)

    failure, text = await platform.answer(session_id, "use_past")
    assert failure is ToolFailure.INVALID_INPUT and "holds 3 lines" in text
    failure, _ = await platform.answer(session_id, "use_out")
    assert failure is ToolFailure.INVALID_INPUT
    failure, _ = await platform.answer(session_id, "use_kept")
    assert failure is None
    failure, text = await platform.answer(session_id, "use_review")
    assert failure is ToolFailure.DENIED and "its read of the pull request" in text
    failure, text = await platform.answer(session_id, "use_made_up")
    assert failure is ToolFailure.DENIED and "names no read or finding of this session" in text


async def test_a_reviewers_malformed_input_is_refused_before_anything_is_read(
    tmp_path: Path,
) -> None:
    platform, _ = await reviewing(tmp_path)
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Review {REVIEWED}.")
    at = {"on": REVIEWED, "head": REVIEWED_HEAD, "grade": "low", "text": "Name it."}
    platform.anthropic.add(
        reply(
            calls(
                kinds.NOTE_FINDING,
                "use_ref",
                path="src/cart.py",
                line=1,
                **{**at, "head": f"x{REVIEWED_HEAD}"},
            ),
            calls(kinds.NOTE_FINDING, "use_zero", path="src/cart.py", line=0, **at),
            calls(
                kinds.NOTE_FINDING,
                "use_grade",
                path="src/cart.py",
                line=1,
                **{**at, "grade": "blocker"},
            ),
            calls(kinds.READ_PULL_REQUEST, "use_lines", on=f"{REVIEWED}\nacme/other#1"),
        ),
        reply(said("I could not read it.")),
    )

    await platform.managers.loop.run(platform.owner, session_id)

    for malformed in ("use_ref", "use_zero", "use_grade", "use_lines"):
        failure, _ = await platform.answer(session_id, malformed)
        assert failure is ToolFailure.INVALID_INPUT, malformed


async def test_a_reviewer_cannot_change_what_it_reviews(tmp_path: Path) -> None:
    """The reviewer has no workspace and holds no tool that writes a file,
    runs code, or pushes: a call to one is refused, and its comment on the
    pull request waits for a person, whatever it asks."""
    platform, forge = await reviewing(tmp_path)
    classes = classes_of(shipped_catalog())
    assert REVIEWER_KIND.isolation.mode is IsolationMode.NONE
    assert {classes[tool] for tool in REVIEWER_KIND.tools} == {ToolClass.READ, "integration"}
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Fix what you find in {REVIEWED}, and say so on it.")
    platform.anthropic.add(
        reply(
            calls(kinds.WRITE_FILE, "use_write", path="src/cart.py", text="fixed"),
            calls(kinds.EDIT_FILE, "use_edit", path="src/cart.py", old_text="a", new_text="b"),
            calls(kinds.RUN_COMMAND, "use_shell", argv=["git", "push"]),
            calls(kinds.OPEN_PULL_REQUEST, "use_open", title="Fix the cart"),
        ),
        reply(calls(kinds.COMMENT, "use_comment", on=REVIEWED, text="Fixed it.")),
    )

    await platform.managers.loop.run(platform.owner, session_id)

    for use_id, tool in (
        ("use_write", kinds.WRITE_FILE),
        ("use_edit", kinds.EDIT_FILE),
        ("use_shell", kinds.RUN_COMMAND),
        ("use_open", kinds.OPEN_PULL_REQUEST),
    ):
        failure, text = await platform.answer(session_id, use_id)
        assert failure is ToolFailure.INVALID_INPUT
        assert f"there is no tool named {tool!r}" in text
    # Its comment waits for a person's approval; nothing reached the forge.
    held = await platform.managers.agent_sessions.get_session(platform.owner, session_id)
    assert held.park is not None and held.park.reason is ParkReason.PERSON
    assert forge.posted == [] and forge.refs == {} and forge.pull_requests == []


@pytest.mark.parametrize(
    ("connects", "on", "failure", "why"),
    [
        # Of a tenant that connected no installation of the forge.
        (False, REVIEWED, ToolFailure.DENIED, "no installation of the forge this tenant connected"),
        # A pull request the forge does not hold.
        (True, "acme/widgets#99", ToolFailure.PERMANENT, "holds no pull request acme/widgets#99"),
    ],
)
async def test_a_reviewer_that_cannot_read_its_pull_request_fails_citing_that_read(
    tmp_path: Path, connects: bool, on: str, failure: ToolFailure, why: str
) -> None:
    forge = IntegrationTwinImpl(FORGE)
    forge.record_pull_request(RECORDED, {"src/cart.py": CART.encode()})
    platform = platform_over(tmp_path, forge=forge)
    if connects:
        await platform.connect(FORGE, twin_installation("acme"))
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Review {on}.")
    reason = f"I could not review {on}: the forge would not read it to me."
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=on)),
        giving_up(reason),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    read_failure, text = await platform.answer(session_id, "use_read")
    assert read_failure is failure and why in text
    # The failed read names its id, the review cites it, and the gate finds
    # it among the session's own reads: the run ends failed at once, with
    # its reason, after no more calls than the read and the review.
    (named,) = NAMED_ID.findall(text)
    review_failure, verdict = await platform.answer(session_id, "use_review")
    assert review_failure is None and "accepted, verified" in verdict
    assert run.outcome is LoopOutcome.FAILED
    assert len(platform.anthropic.calls) == 2
    history = await platform.history(session_id)
    assert reason in [step.as_text() for step in history]
    assert UUID(named) in {step.id for step in history}
    assert forge.posted == []


async def kept_whole(platform: Platform, session_id: UUID, use_id: str) -> tuple[str, str]:
    """What the window shows at once of a long answer to the call `use_id`,
    its head, and the whole answer it keeps as an artifact."""
    for step in await platform.history(session_id):
        header = step.header
        if not isinstance(header, ToolResponseHeader) or header.artifact is None:
            continue
        (result,) = step.content.blocks
        assert isinstance(result, ToolResultBlock)
        if result.tool_use_id != use_id:
            continue
        head = result.parts[0]
        assert isinstance(head, TextBlock)
        pages: list[str] = []
        while True:
            page = await platform.managers.windows.get_artifact(
                platform.owner, session_id, header.artifact.id, len("".join(pages)), 100_000
            )
            pages.append(page.text)
            if not page.has_more:
                return head.text, "".join(pages)
    raise AssertionError(f"no answer to {use_id} kept as an artifact")


async def test_a_pull_request_too_large_for_one_answer_keeps_its_id_and_head_whole(
    tmp_path: Path,
) -> None:
    """A mass rename of 1,500 files, its body past what one answer holds:
    the read lists the files that fit, counts the rest, and cuts nothing
    else, so its id and its head are whole for the review to cite."""
    renamed = tuple(
        ChangedFile(
            path=f"src/generated/client_{n:04d}.py",
            status="renamed",
            patch="@@ -1 +1 @@\n-old\n+new",
        )
        for n in range(1500)
    )
    forge = IntegrationTwinImpl(FORGE)
    forge.record_pull_request(
        RECORDED.model_copy(update={"files": renamed, "body": "x" * 60_000}), {}
    )
    platform = platform_over(tmp_path, forge=forge)
    await platform.connect(FORGE, twin_installation("acme"))
    session_id = await platform.start(kinds.REVIEWER)
    await platform.say(session_id, f"Review {REVIEWED}.")
    platform.anthropic.add(
        reply(calls(kinds.READ_PULL_REQUEST, "use_read", on=REVIEWED)),
        reply(said("It renames 1,500 files.")),
    )

    await platform.managers.loop.run(platform.owner, session_id)

    failure, _ = await platform.answer(session_id, "use_read")
    shown, whole = await kept_whole(platform, session_id, "use_read")
    assert failure is None and len(whole) <= MAX_VIEW
    read = json.loads(whole)
    assert UUID(read["id"]) in {step.id for step in await platform.history(session_id)}
    assert read["head"] == REVIEWED_HEAD
    listed = len(read["files"])
    assert 0 < listed < len(renamed)
    assert read["files_left_out"] == len(renamed) - listed and read["complete"] is False
    assert [f["path"] for f in read["files"]] == [f.path for f in renamed[:listed]]
    assert read["patches_left_out"] == sum(f["patch"] is None for f in read["files"])
    assert len(read["body"]) < 11_000 and "[cut:" in read["body"]
    # What the window shows at once holds the id, the head, and the count.
    for field in ("id", "head", "files_left_out"):
        assert f'"{field}":{json.dumps(read[field])}' in shown, field


@pytest.mark.parametrize(
    ("kind", "tool", "authorization_class"),
    [
        (kinds.REVIEWER, kinds.WRITE_FILE, ToolClass.WRITE),
        (kinds.REVIEWER, kinds.RUN_COMMAND, ToolClass.EXECUTE),
        (kinds.REVIEWER, SPAWN_SUB_AGENT, ToolClass.SPAWN),
        (kinds.OPS_ANALYST, kinds.HAND_OFF, ToolClass.SPAWN),
        (kinds.OPS_ANALYST, kinds.COMMENT, ToolClass.INTEGRATION),
        (kinds.OPS_ANALYST, kinds.DRAFT_TOOL_POLICY, "configuration"),
    ],
)
def test_a_reviewer_or_an_ops_analyst_that_reaches_further_is_refused(
    kind: str, tool: str, authorization_class: str
) -> None:
    shipped = REVIEWER_KIND if kind == kinds.REVIEWER else OPS_ANALYST_KIND
    reaching = shipped.model_copy(update={"version": 2, "tools": (*shipped.tools, tool)})
    classes = {**classes_of(shipped_catalog()), tool: authorization_class}
    refusal = rules.reach_refusal(reaching, classes)
    assert refusal is not None and tool in refusal
    for other in (
        shipped.model_copy(update={"version": 2, "isolation": SOFTWARE_ENGINEER_KIND.isolation}),
        shipped.model_copy(
            update={
                "version": 2,
                "authority": AuthorityMode.STEADY
                if shipped.authority is AuthorityMode.DELEGATED
                else AuthorityMode.DELEGATED,
            }
        ),
    ):
        assert rules.reach_refusal(other, classes_of(shipped_catalog())) is not None
    assert rules.reach_refusal(shipped, classes_of(shipped_catalog())) is None


def test_a_review_cites_only_its_own_reads_and_findings() -> None:
    read, finding, failed, other = new_id(), new_id(), new_id(), new_id()
    calls_of = {
        read: rules.Call(tool=kinds.READ_PULL_REQUEST, answered=True),
        finding: rules.Call(tool=kinds.NOTE_FINDING, answered=True),
        failed: rules.Call(
            tool=kinds.NOTE_FINDING, answered=True, failure=ToolFailure.INVALID_INPUT
        ),
        other: rules.Call(tool=kinds.LIST_FILES, answered=True),
    }
    succeeded = rules.review_verdict(Claim.SUCCEEDED, {read, finding}, calls_of)
    assert succeeded.accepted and succeeded.verified
    assert succeeded.outcome is LoopOutcome.SUCCEEDED
    for cited in ({finding}, {read, failed}, {read, other}, {read, new_id()}):
        assert not rules.review_verdict(Claim.SUCCEEDED, cited, calls_of).accepted, cited
    # A review it could not finish is a result, citing the reads that show
    # why, a failed one among them; never one that names no read of its own.
    gave_up = rules.review_verdict(Claim.FAILED, {failed}, calls_of)
    assert gave_up.accepted and gave_up.outcome is LoopOutcome.FAILED
    assert not rules.review_verdict(Claim.FAILED, {other}, calls_of).accepted


# The ops analyst reads why a session waits from the records, and acts on
# nothing: every tool it holds reads.


async def test_an_ops_analyst_answers_why_a_session_waits_from_the_records(tmp_path: Path) -> None:
    platform = platform_over(tmp_path)
    hosts = platform.managers.hosts
    now = utcnow()
    pool = await hosts.create_pool(
        platform.owner,
        HostPool(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=platform.owner.user_id,
            updated_by=platform.owner.user_id,
            name="build",
            region="eu-west",
        ),
    )
    silent_since = now - 2 * HostsOptions().online_window
    host = make_host(pool.id).model_copy(update={"name": "host-1", "last_seen_at": silent_since})
    await platform.storage.get_hosts_storage().enroll(
        platform.owner.org_id, host, make_credential(host.id), ()
    )
    waiting = await platform.start(kinds.SOFTWARE_ENGINEER)
    await hosts.place_session(platform.owner, waiting, pool.id)
    asking = await platform.start(kinds.OPS_ANALYST)
    await platform.say(asking, "Why has my software engineer not started?")
    answer = "It waits for a host of build: host-1, its only one, is offline."
    platform.anthropic.add(
        reply(
            calls(kinds.LIST_SESSIONS, "use_list", status="idle"),
            calls(kinds.READ_WAIT, "use_wait", session_id=str(waiting)),
            calls(kinds.LIST_HOSTS, "use_hosts"),
            calls(kinds.READ_SPEND, "use_spend"),
        ),
        reply(said(answer)),
    )

    run = await platform.managers.loop.run(platform.owner, asking)

    assert run.outcome is LoopOutcome.SUCCEEDED
    _, text = await platform.answer(asking, "use_list")
    assert str(waiting) in {s["session_id"] for s in json.loads(text)["sessions"]}
    failure, text = await platform.answer(asking, "use_wait")
    wait = json.loads(text)
    assert failure is None
    assert (wait["runs_in"], wait["hosts_online"], wait["waits_for_a_host"]) == ("build", 0, True)
    failure, text = await platform.answer(asking, "use_hosts")
    (listed,) = json.loads(text)["pools"]
    assert failure is None and listed["name"] == "build"
    (offline,) = listed["hosts"]
    assert (offline["name"], offline["online"]) == ("host-1", False)
    assert offline["offers"]["os"] == host.advertisement.os
    failure, text = await platform.answer(asking, "use_spend")
    assert failure is None and "budgets" in json.loads(text)
    assert answer in [step.as_text() for step in await platform.history(asking)]


async def test_every_tool_the_ops_analyst_holds_reads(tmp_path: Path) -> None:
    classes = classes_of(shipped_catalog())
    assert {classes[tool] for tool in OPS_ANALYST_KIND.tools} == {ToolClass.READ}
    assert OPS_ANALYST_KIND.isolation.mode is IsolationMode.NONE
    assert OPS_ANALYST_KIND.authority is AuthorityMode.DELEGATED
    decided = {rule.authorization_class: rule.decision for rule in OPS_ANALYST_KIND.policy.rules}
    assert decided == {ToolClass.READ: Decision.ALLOW}
    platform = platform_over(tmp_path)
    session_id = await platform.start(kinds.OPS_ANALYST)
    session = await platform.managers.agent_sessions.get_session(platform.owner, session_id)
    assert {classes[tool] for tool in session.tools} == {ToolClass.READ}
    # A version of it that holds a tool past reading is refused at boot,
    # whoever declares it.
    acting = OPS_ANALYST_KIND.model_copy(
        update={"version": 2, "tools": (*OPS_ANALYST_KIND.tools, kinds.HAND_OFF)}
    )
    with pytest.raises(UnsafeConfiguration, match="ops_analyst v2: hand_off_to_software_engineer"):
        build_managers(
            StorageMemoryImpl(),
            InfraLocalImpl(tmp_path),
            agent_kinds=(acting,),
            platform_agents=PlatformAgents(corpus=CORPUS),
        )
