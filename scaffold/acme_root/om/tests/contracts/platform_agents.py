"""The platform's agents over a storage: the managers with the shipped kinds
and tools, the scripted model of each provider, and what the suites read
back. Nothing here reaches a network, and no case waits on the wall
clock."""

from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.calls import ModelCall, ModelReply, StreamPart
from acme.integrations.model_providers.registry import ModelProvidersOverImpl
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl, ScriptedFailure
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.impl.loop import LoopOptions
from acme.om.agents.types.kind import AgentKind
from acme.om.agents.types.request import Start
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.automations import AutomationsManagerInterface
from acme.om.automations.root import build_automations
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.evidence import ExecutorInterface, WorkProductInterface
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.rules import TENANT_USERS
from acme.om.platform_agents.types.corpus import Corpus, Document
from acme.om.root import Managers, ProductKinds, build_managers
from acme.om.steps.types.content import TextBlock, ToolResultBlock, ToolUseBlock
from acme.om.steps.types.header import ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import Step, StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from contracts.doubles import context
from contracts.factories import make_org
from contracts.loops import live
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
