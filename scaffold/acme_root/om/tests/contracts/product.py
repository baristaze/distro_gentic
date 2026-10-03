"""A product's own parts, declared once as a product declares them in
`PRODUCT_KINDS`: an agent kind of its own, a tool that reads a manager,
and the authorization class that tool declares beside the platform's."""

from collections.abc import Callable
from datetime import timedelta

from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import Platform
from acme.om.context import TenantContext
from acme.om.platform_agents.tools import NativeToolImpl
from acme.om.root import Managers, ProductKinds
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import Effect, ToolInput, ToolMode, ToolSpec

LEDGER_CLASS = "ledger"
"""The class the product's tool declares, which no class of the platform's
names."""


class Nothing(ToolInput):
    pass


class Title(Platform):
    title: str


class ReadTitleImpl(NativeToolImpl):
    """Reads the title of the session it runs in, through the agent
    sessions' manager, which the root answers when the tool is called."""

    SPEC = ToolSpec(
        name="read_title",
        description="Reads the title of the session it runs in.",
        input_model=Nothing,
        output_model=Title,
        timeout=timedelta(seconds=10),
        authorization_class=LEDGER_CLASS,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, managers: Callable[[], Managers], read: list[str]) -> None:
        self._managers = managers
        self._read = read

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        session = await self._managers().agent_sessions.get_session(ctx, runtime.session_id)
        self._read.append(session.title)
        return Title(title=session.title)


LEDGER = AgentKind(
    name="ledger",
    version=1,
    tools=(ReadTitleImpl.SPEC.name,),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
    prompts=("Answer from the ledger.",),
    policy=PolicyLayer(
        rules=(PolicyRule(authorization_class=LEDGER_CLASS, decision=Decision.ALLOW),)
    ),
    isolation=NO_WORKSPACE,
)
"""The product's own kind: it reads through its tool and answers."""


def ledger_product(read: list[str]) -> ProductKinds:
    """The product's parts, its tool keeping each title it read in `read`."""

    def tools(managers: Callable[[], Managers]) -> tuple[ToolInterface, ...]:
        return (ReadTitleImpl(managers, read),)

    return ProductKinds(agents=(LEDGER,), tools=tools, classes=(LEDGER_CLASS,))
