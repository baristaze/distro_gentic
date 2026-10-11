"""The platform's agents over a storage: the managers with the shipped kinds
and tools, the scripted model of each provider, what the suites read back,
and the cases the suite over memory and the suite over Postgres both run.
Nothing here reaches a network, and no case waits on the wall clock."""

import json
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.calls import ModelCall, ModelReply, StreamPart
from acme.integrations.model_providers.registry import ModelProvidersOverImpl
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl, ScriptedFailure
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
from acme.om.agents.impl.loop import LoopOptions
from acme.om.agents.rules import CHILDREN_PARK
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind
from acme.om.agents.types.request import Start
from acme.om.agents.types.result import Claim
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations import AutomationsManagerInterface
from acme.om.automations.root import build_automations
from acme.om.base import new_id
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind, WindowKind
from acme.om.context import Role, TenantContext
from acme.om.evidence import ExecutorInterface, WorkProductInterface
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.validation import Delivery
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.kinds import ANALYSIS_KIND, ANALYSIS_SHARE, ENGINEER_KIND
from acme.om.platform_agents.rules import TENANT_USERS
from acme.om.platform_agents.types.corpus import Corpus, Document
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.content import TextBlock, ToolResultBlock, ToolUseBlock
from acme.om.steps.types.header import LoopOutcome, ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import Step, StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.native.spawn_sub_agent import SPAWN_SUB_AGENT
from acme.om.tools.native.wait_for_sub_agents import WAIT_FOR_SUB_AGENTS
from contracts.budget_storage import make_budget
from contracts.doubles import context
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from contracts.factories import make_org
from contracts.loops import live, reply, said
from contracts.project_storage import in_project, make_binding
from contracts.step_storage import make_message

SESSIONS_GUIDE = Document(
    title="Sessions",
    path="om/README.md",
    text=(
        "# Sessions\n\nA session is a series of loops over one history.\n\n"
        "## Why a session waits\n\nA pending session waits in its lane while its "
        "tenant's loops are at their fair share, and runs when one of them ends.\n"
    ),
)
CORPUS = Corpus(audience=TENANT_USERS, documents=(SESSIONS_GUIDE,))


Later = Callable[[ModelCall], ModelReply]
"""A turn made when its call comes, from what the model reads in it."""


class ModelProviderReadingImpl(ModelProviderScriptedImpl):
    """The scripted twin, whose turns may also be made when their call
    comes: a turn that cites what a tool answered, which no script knows
    before the tool runs."""

    def __init__(self, provider: ProviderName) -> None:
        super().__init__(provider)
        self._turns: deque[ModelReply | ScriptedFailure | Later] = deque()

    def add(self, *turns: ModelReply | ScriptedFailure | Later) -> None:
        self._turns.extend(turns)

    async def stream(
        self, call: ModelCall, *, credential: SecretStr | None = None
    ) -> AsyncIterator[StreamPart]:
        if self._turns:
            turn = self._turns.popleft()
            ModelProviderScriptedImpl.add(self, turn if not callable(turn) else turn(call))
        async for part in super().stream(call, credential=credential):
            yield part


@dataclass
class Platform:
    storage: StorageInterface
    managers: Managers
    anthropic: ModelProviderReadingImpl
    openai: ModelProviderScriptedImpl
    owner: TenantContext
    automations: AutomationsManagerInterface

    async def start(self, kind: str) -> UUID:
        session = await self.managers.agents.start_session(
            self.owner, Start(id=new_id(), kind=kind, title="a question")
        )
        return session.id

    async def say(self, session_id: UUID, text: str) -> None:
        person = Principal(kind=PrincipalKind.PERSON, id=self.owner.user_id)
        message = make_message(session_id, text, principal=person)
        await self.managers.steps.append_inputs(self.owner, session_id, [message])

    async def history(self, session_id: UUID) -> list[Step]:
        steps: list[Step] = []
        while True:
            after = steps[-1].seq if steps else 0
            page = await self.managers.steps.get_steps(self.owner, session_id, after, 200)
            steps.extend(page.items)
            if not page.has_more or not page.items:
                return steps

    async def answer(self, session_id: UUID, use_id: str) -> tuple[ToolFailure | None, str]:
        """What the call `use_id` was answered: its failure, if any, and its
        text."""
        for step in await self.history(session_id):
            if step.type is not StepType.TOOL_RESPONSE:
                continue
            for block in step.content.blocks:
                if isinstance(block, ToolResultBlock) and block.tool_use_id == use_id:
                    header = step.header
                    assert isinstance(header, ToolResponseHeader)
                    texts = [p.text for p in block.parts if isinstance(p, TextBlock)]
                    return header.failure, "\n".join(texts)
        raise AssertionError(f"no answer to {use_id}")

    def model_calls(self) -> int:
        return len(self.anthropic.calls) + len(self.openai.calls)


def platform_over(
    tmp_path: Path,
    *,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
    corpus: Corpus = CORPUS,
    kinds: tuple[AgentKind, ...] = (),
    executor: ExecutorInterface | None = None,
    work_product: WorkProductInterface | None = None,
    product_kinds: ProductKinds | None = None,
) -> Platform:
    """The managers with the platform's agents shipped over `corpus`, each
    principal a member of the tenant at every call, and the automations the
    assistant reads, built over them. `storage` None is the memory storage,
    and `owner` None a fresh tenant's owner; a suite over Postgres hands in
    both. `kinds` are the adopter's beside the shipped ones, `executor` and
    `work_product` the evidence's ports, None the root's own, and
    `product_kinds` what a product adds, None nothing."""
    anthropic = ModelProviderReadingImpl(ProviderName.ANTHROPIC)
    openai = ModelProviderScriptedImpl(ProviderName.OPENAI)
    providers = ModelProvidersOverImpl(
        {ProviderName.ANTHROPIC: anthropic, ProviderName.OPENAI: openai}
    )
    storage = storage or StorageMemoryImpl()
    automations: list[AutomationsManagerInterface] = []
    managers = build_managers(
        storage,
        InfraLocalImpl(tmp_path),
        integrations=IntegrationsOverImpl(IdentityProviderAbsentImpl(), providers),
        principal_context=live,
        loop_options=LoopOptions(control_poll=timedelta(milliseconds=1)),
        platform_agents=PlatformAgents(corpus=corpus),
        agent_kinds=kinds,
        executor=executor,
        work_product=work_product,
        product_kinds=product_kinds,
        automations=lambda: automations[0],
    )
    automations.append(build_automations(storage, managers, project_required=False))
    owner = owner or context(Role.OWNER, make_org())
    return Platform(storage, managers, anthropic, openai, owner, automations[0])


def calls(name: str, use_id: str, **tool_input: object) -> ToolUseBlock:
    return ToolUseBlock(id=use_id, name=name, input=tool_input)


# The shipped kinds in the workspace a suite prepares.

TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))
"""The workspace the suites prepare, in place of a container."""


def on_the_twin(kind: AgentKind) -> AgentKind:
    """The shipped profile, whole, in the workspace a suite can prepare."""
    return kind.model_copy(update={"version": kind.version + 1, "isolation": TWIN})


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


# The engineer starts sub-agents.


def sub_agents_over(
    tmp_path: Path, *, storage: StorageInterface | None = None
) -> tuple[Platform, ScriptedExecutor, WorkProductMemoryImpl]:
    """The platform with the shipped engineer on the twin, and analysis with
    no workspace: a sub-agent belongs to its parent's project, whose
    repository no suite can fetch, and the case's sub-agents read none."""
    executor = ScriptedExecutor(capabilities=frozenset())
    work = WorkProductMemoryImpl()
    reader = ANALYSIS_KIND.model_copy(
        update={"version": ANALYSIS_KIND.version + 1, "isolation": NO_WORKSPACE}
    )
    platform = platform_over(
        tmp_path,
        storage=storage,
        kinds=(on_the_twin(ENGINEER_KIND), reader),
        executor=executor,
        work_product=work,
    )
    return platform, executor, work


TREE_CAP = 5_000_000
"""The root's budget: far below what its two sub-agents' shares add up to,
so the tree's budget, not a share, is what bounds the tree."""


def read_by(call: ModelCall) -> str:
    """Every text a model call reads."""
    return "\n".join(
        block.text
        for message in call.messages
        for block in message.blocks
        if isinstance(block, TextBlock)
    )


async def a_parked_root(platform: Platform, root: UUID) -> AgentSession:
    session = await platform.managers.agent_sessions.get_session(platform.owner, root)
    assert (session.status, session.park) == (SessionStatus.PARKED, CHILDREN_PARK)
    return session


async def a_woken_root(platform: Platform, root: UUID) -> None:
    session = await platform.managers.agent_sessions.get_session(platform.owner, root)
    assert (session.status, session.park) == (SessionStatus.PENDING, None), "a report wakes it"


async def an_engineer_starts_two_sub_agents_and_wakes_on_each_report(
    platform: Platform, executor: ScriptedExecutor, work: WorkProductMemoryImpl
) -> None:
    """The shipped engineer takes its baseline, then starts two analysis
    sub-agents in one turn and parks on them. Each report wakes it: it reads
    the first and waits on the second, reads the second, validates its
    head, and ends through its result gate. Each sub-agent runs under its share in the root's project,
    and what the whole tree spent and holds stays within the root's budget,
    which is far below the shares added up."""
    projects = platform.storage.get_project_storage()
    project_id = await in_project(projects, platform.owner.org_id)
    await platform.managers.evidence.write_policy(
        platform.owner, make_policy(policy_key(project_id))
    )
    executor.outcome = lambda check, trial: "passed"
    root = await an_engineer(platform, work, project_id)
    budget = await platform.managers.budgets.create_budget(
        platform.owner,
        make_budget(BudgetScopeKind.TREE, str(root), window=WindowKind.LIFE, cost_micros=TREE_CAP),
    )
    assert TREE_CAP < 2 * (ANALYSIS_SHARE.cost_micros or 0)
    split = (
        ("the empty week", "Read report.log and say whether a week with no rows drops the total."),
        (
            "the callers",
            "Find every caller of total() under src/ and say which skip an empty week.",
        ),
    )
    platform.anthropic.add(
        reply(calls(kinds.VALIDATE, "use_baseline", baseline=True)),
        reply(
            said("Two things decide this; a sub-agent looks at each."),
            *(
                calls(
                    SPAWN_SUB_AGENT,
                    f"use_spawn_{n}",
                    title=title,
                    objective=objective,
                    kind=kinds.ANALYSIS,
                )
                for n, (title, objective) in enumerate(split, 1)
            ),
            calls(WAIT_FOR_SUB_AGENTS, "use_wait_1"),
        ),
    )

    parked = await platform.managers.loop.run(platform.owner, root)

    assert parked.end is RunEnd.PARKED and parked.park == CHILDREN_PARK
    await a_parked_root(platform, root)
    page = await platform.managers.agent_sessions.get_children(platform.owner, root, None, 50)
    first, second = sorted(page.items, key=lambda child: [t for t, _ in split].index(child.title))
    assert [(child.kind, child.depth) for child in (first, second)] == [(kinds.ANALYSIS, 2)] * 2
    failure, text = await platform.answer(root, "use_wait_1")
    assert failure is None and str(first.id) in text and str(second.id) in text
    budgets = await platform.managers.budgets.get_budgets(platform.owner, None, 50)
    for child in (first, second):
        scope = BudgetScope(kind=BudgetScopeKind.SESSION, key=str(child.id))
        assert [b.amount for b in budgets.items if b.scope == scope] == [ANALYSIS_SHARE]
        project = await platform.managers.projects.project_of(platform.owner, child.id)
        assert project is not None and project.id == project_id, "in its root's project"

    # The first reports: the root wakes, reads it, and waits on the second.
    platform.anthropic.add(reply(said("A week with no rows drops the total (report.log:12).")))
    assert (
        await platform.managers.loop.run(platform.owner, first.id)
    ).outcome is LoopOutcome.SUCCEEDED
    await a_woken_root(platform, root)
    before = len(platform.anthropic.calls)
    platform.anthropic.add(reply(calls(WAIT_FOR_SUB_AGENTS, "use_wait_2")))

    waits = await platform.managers.loop.run(platform.owner, root)

    assert waits.end is RunEnd.PARKED and waits.park == CHILDREN_PARK
    await a_parked_root(platform, root)
    assert "drops the total (report.log:12)" in read_by(platform.anthropic.calls[before])
    failure, text = await platform.answer(root, "use_wait_2")
    assert failure is None and str(second.id) in text and str(first.id) not in text

    # The second reports: the root wakes, reads it, validates, and ends.
    platform.anthropic.add(reply(said("Only src/report.py calls total(), and it skips none.")))
    assert (
        await platform.managers.loop.run(platform.owner, second.id)
    ).outcome is LoopOutcome.SUCCEEDED
    await a_woken_root(platform, root)
    before = len(platform.anthropic.calls)
    platform.anthropic.add(reply(calls(kinds.VALIDATE, "use_validate")), citing(Claim.SUCCEEDED))

    ended = await platform.managers.loop.run(platform.owner, root)

    assert ended.outcome is LoopOutcome.SUCCEEDED
    assert "it skips none" in read_by(platform.anthropic.calls[before])
    failure, text = await platform.answer(root, "use_succeeded")
    assert failure is None and "verified" in text and "unverified" not in text

    # What the tree spent: each sub-agent's calls and the root's, together
    # within the root's budget.
    tally = await platform.managers.budgets.get_spend(platform.owner, budget.id)
    assert tally.held_cost_micros == 0
    assert 0 < tally.spent_cost_micros <= TREE_CAP
    spent = []
    for child in (first, second):
        scope = BudgetScope(kind=BudgetScopeKind.SESSION, key=str(child.id))
        (share,) = [b for b in budgets.items if b.scope == scope]
        spent.append(
            (await platform.managers.budgets.get_spend(platform.owner, share.id)).spent_cost_micros
        )
    assert all(child > 0 for child in spent), "each sub-agent spent from the tree"
    assert sum(spent) < tally.spent_cost_micros, "and the root spent from it too"
