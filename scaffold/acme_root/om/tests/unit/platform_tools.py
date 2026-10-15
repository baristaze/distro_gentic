"""What the platform agents' suite and its tools' suites share: a stand-in
for a manager no case reaches, the tools manager over a directory on this
host and a tool's call run there as the loop runs one, and a pull request
the forge holds for the reviewer to read."""

from pathlib import Path

from acme.infra.agent_workspaces import AgentWorkspace
from acme.infra.agent_workspaces.host import AgentWorkspaceHostImpl
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerTwinImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.integrations.events import ChangedFile, CheckRun, PullRequestRead
from acme.integrations.events.twin import IntegrationTwinImpl, twin_installation
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.context import TenantContext
from acme.om.intake.tools import FORGE
from acme.om.tools.tool import ToolInterface

from contracts.platform_agents import Platform, platform_over
from contracts.tools import Tools, put_call, registry_of, tools_over


def unbound() -> object:
    raise AssertionError("no manager is reached while the catalog is read")


def on_the_host(tmp_path: Path) -> Tools:
    transport = TransportLocalImpl(
        tmp_path / "records", SecretsLocalImpl(None, {}), BrokerTwinImpl()
    )
    return tools_over(transport, AgentWorkspaceHostImpl(tmp_path / "workspaces"))


async def called(
    tools: Tools,
    tool: ToolInterface,
    ctx: TenantContext,
    workspace: AgentWorkspace,
    **call_input: object,
) -> AgentStep:
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
