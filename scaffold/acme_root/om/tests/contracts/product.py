"""A product's own parts, declared once as a product declares them in
`PRODUCT_KINDS`: an agent kind of its own, a tool that reads a manager,
and the authorization class that tool declares beside the platform's."""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from types import ModuleType

from acme.om.agents.prompts import LOCK, PROMPTS, digest
from acme.om.agents.types.kind import NO_AGENT_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.platform_agents.folders import MANUALS, KindFolder, folder_of
from acme.om.platform_agents.tools.base import NativeToolImpl
from acme.om.platform_root import PlatformManagers, ProductKinds
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import Decision, Target, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import Effect, ToolInput, ToolMode, ToolSpec

LEDGER_CLASS = "ledger"
"""The class the product's tool declares, which no class of the platform's
names."""


class Nothing(ToolInput):
    pass


class Title(OmBase):
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

    def __init__(self, managers: Callable[[], PlatformManagers], read: list[str]) -> None:
        self._managers = managers
        self._read = read

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        # It reads the session it runs in and nothing else, so its call stays
        # in the session's own work, whatever its product class would say.
        return Target(attributes={"outward": False})

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        sessions = self._managers().agent_sessions
        session = await sessions.get_agent_session(ctx, runtime.agent_session_id)
        (opened,) = await sessions.open_titles(ctx, [session])
        self._read.append(opened.title.said())
        return Title(title=opened.title.said())


LEDGER = AgentKind(
    name="ledger",
    version=1,
    tools=(ReadTitleImpl.SPEC.name,),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
    prompts=("Answer from the ledger.",),
    policy=ToolPolicyLayer(
        rules=(ToolPolicyRule(authorization_class=LEDGER_CLASS, decision=Decision.ALLOW),)
    ),
    isolation=NO_AGENT_WORKSPACE,
)
"""The product's own kind: it reads through its tool and answers."""


LEDGER_MANUAL = "Name the ledger's account for every total you give."
"""The manual the product's kind ships in its folder."""


def ledger_folder(where: Path) -> KindFolder:
    """The product's kind as a product keeps it, a folder of its own under
    `where`: its prompt pinned in its lock, and one manual."""
    folder = where / LEDGER.name
    (folder / PROMPTS).mkdir(parents=True)
    (prompt,) = LEDGER.prompts
    (folder / PROMPTS / "v1.md").write_text(prompt + "\n", encoding="utf-8")
    (folder / PROMPTS / LOCK).write_text(json.dumps({"v1.md": digest(prompt)}), encoding="utf-8")
    (folder / MANUALS).mkdir()
    (folder / MANUALS / "answers.md").write_text(LEDGER_MANUAL + "\n", encoding="utf-8")
    module = ModuleType(LEDGER.name)
    module.__file__ = str(folder / "kind.py")
    module.VERSIONS = (LEDGER,)  # pyright: ignore[reportAttributeAccessIssue]
    return folder_of(module)


def ledger_product(read: list[str], folder: KindFolder | None = None) -> ProductKinds:
    """The product's parts, its tool keeping each title it read in `read`;
    its kind declared alone, or as `folder` when one is given."""

    def tools(managers: Callable[[], PlatformManagers]) -> tuple[ToolInterface, ...]:
        return (ReadTitleImpl(managers, read),)

    if folder is None:
        return ProductKinds(agents=(LEDGER,), tools=tools, classes=(LEDGER_CLASS,))
    return ProductKinds(folders=(folder,), tools=tools, classes=(LEDGER_CLASS,))
