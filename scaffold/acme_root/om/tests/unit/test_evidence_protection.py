"""An agent's edit to a protected path is refused: a tool that changes
files reports the paths it changes as its target, the policy of the
session's project says whether one is protected, and the platform's
ceiling denies the call whatever the kind's defaults and the tenant's layer
allow. The engineer's own `write_file` and `edit_file` refuse it at the
call."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.evidence import checkout_policy, evidence_over
from contracts.factories import make_org
from contracts.tools import put_call, registry_of, result_text, tools_over, twin_transport

from acme.infra.impl.local import InfraLocalImpl
from acme.infra.workspaces import Workspace
from acme.om.base import Platform, new_id
from acme.om.context import Role, TenantContext
from acme.om.evidence.manager import EvidenceManagerInterface
from acme.om.evidence.rules import CEILINGS, PROTECTED_CEILING
from acme.om.platform_agents.tools import EditFileImpl, WriteFileImpl
from acme.om.root import build_managers
from acme.om.steps.types.header import ToolFailure, ToolResponseHeader
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.impl.manager import ToolsOptions
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.call import GateOutcome
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule, Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolSpec


class WriteInput(ToolInput):
    path: str
    text: str
    # What a model may fill in to vouch for its call; policy never reads it.
    protected: bool = False


class Written(Platform):
    path: str


class WriteFile(ToolInterface):
    """Writes one file of a session's work product. Whether the path is
    protected is read from the policy of the session's project, never from
    the input."""

    def __init__(self, evidence: EvidenceManagerInterface, session_id: UUID) -> None:
        self._evidence = evidence
        self._session_id = session_id
        self.written: list[str] = []
        self._spec = ToolSpec(
            name="write_file",
            description="Writes a file.",
            input_model=WriteInput,
            output_model=Written,
            timeout=timedelta(seconds=30),
            authorization_class=ToolClass.WRITE,
            effect=Effect.IDEMPOTENT,
            interruptible=False,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        assert isinstance(call_input, WriteInput)
        return await self._evidence.protection(ctx, self._session_id, [call_input.path])

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        return None

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, WriteInput)
        self.written.append(call_input.path)
        return Written(path=call_input.path)


ALLOW_WRITES = PolicyLayer(
    rules=(PolicyRule(authorization_class=ToolClass.WRITE, decision=Decision.ALLOW),)
)


async def test_an_agents_edit_to_a_protected_path_is_refused(tmp_path: Path) -> None:
    org = make_org()
    evidence = evidence_over()
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    tools = tools_over(twin_transport(tmp_path)[0], options=ToolsOptions(ceilings=CEILINGS))
    admin = context(Role.ADMIN, org)
    # The tenant lets every write run unattended, as the kind does.
    policy = await tools.manager.get_policy(admin)
    await tools.manager.write_policy(admin, policy.model_copy(update={"rules": ALLOW_WRITES.rules}))
    ctx = context(Role.SERVICE, org)
    write = WriteFile(evidence.manager, new_id())
    registry = registry_of(write)
    workspace = Workspace.absent(ctx.org_id, new_id())
    for path, claim in (
        ("tests/test_cart.py", {}),
        ("tests/test_cart.py", {"protected": False}),
        ("./TESTS/fixtures/orders.json", {}),
    ):
        call = await put_call(
            tools.manager,
            tools.steps,
            ctx,
            "write_file",
            {"path": path, "text": "x", **claim},
            "write",
        )
        gate = await tools.manager.gate(
            ctx, registry, ALLOW_WRITES, call.request, call.call_input, workspace
        )
        assert gate.outcome is GateOutcome.REFUSE and gate.decision is Decision.DENY, path
        assert gate.response is not None
        header = gate.response.header
        assert isinstance(header, ToolResponseHeader) and header.failure is ToolFailure.DENIED
    free = await put_call(
        tools.manager, tools.steps, ctx, "write_file", {"path": "src/cart.py", "text": "x"}, "write"
    )
    gate = await tools.manager.gate(
        ctx, registry, ALLOW_WRITES, free.request, free.call_input, workspace
    )
    assert gate.outcome is GateOutcome.RUN and gate.decision is Decision.ALLOW
    assert write.written == [], "the gate runs nothing"


@pytest.mark.parametrize("pattern", ["tests/", "tests"])
async def test_a_folder_a_policy_protects_refuses_an_edit_inside_it(
    pattern: str, tmp_path: Path
) -> None:
    org = make_org()
    evidence = evidence_over()
    await evidence.manager.write_policy(
        context(Role.OWNER, org), checkout_policy(protected=(pattern,))
    )
    tools = tools_over(twin_transport(tmp_path)[0], options=ToolsOptions(ceilings=CEILINGS))
    ctx = context(Role.SERVICE, org)
    call = await put_call(
        tools.manager,
        tools.steps,
        ctx,
        "write_file",
        {"path": "tests/test_x.py", "text": "x"},
        "write",
    )
    registry = registry_of(WriteFile(evidence.manager, new_id()))
    workspace = Workspace.absent(ctx.org_id, new_id())
    gate = await tools.manager.gate(
        ctx, registry, ALLOW_WRITES, call.request, call.call_input, workspace
    )
    assert gate.outcome is GateOutcome.REFUSE and gate.decision is Decision.DENY


@pytest.mark.parametrize(
    ("tool", "change"),
    [
        ("write_file", {"text": "x"}),
        ("edit_file", {"old_text": "a", "new_text": "b"}),
        ("edit_file", {"start_line": 1, "end_line": 1, "new_text": "b"}),
    ],
)
async def test_the_engineers_change_to_a_protected_path_is_refused_at_the_call(
    tool: str, change: dict[str, object], tmp_path: Path
) -> None:
    org = make_org()
    evidence = evidence_over()
    await evidence.manager.write_policy(context(Role.OWNER, org), checkout_policy())
    tools = tools_over(twin_transport(tmp_path)[0], options=ToolsOptions(ceilings=CEILINGS))
    ctx = context(Role.SERVICE, org)
    impls = {"write_file": WriteFileImpl, "edit_file": EditFileImpl}
    registry = registry_of(impls[tool](lambda: evidence.manager))
    # A session of `checkout`, whose policy protects `tests/`, and one of a
    # project that declares no policy.
    elsewhere = new_id()
    evidence.projects.sessions[elsewhere] = new_id()
    for session_id, refused in ((new_id(), True), (elsewhere, False)):
        workspace = Workspace.absent(ctx.org_id, session_id)
        call = await put_call(
            tools.manager,
            tools.steps,
            ctx,
            tool,
            {"path": "tests/test_cart.py", **change},
            "write",
            session_id,
        )
        gate = await tools.manager.gate(
            ctx, registry, ALLOW_WRITES, call.request, call.call_input, workspace
        )
        if not refused:
            assert gate.outcome is GateOutcome.RUN
            continue
        assert gate.outcome is GateOutcome.REFUSE and gate.response is not None
        header = gate.response.header
        assert isinstance(header, ToolResponseHeader) and header.failure is ToolFailure.DENIED
        assert "is protected" in result_text(gate.response), "the model reads why"


async def test_the_root_keeps_the_protected_ceiling_whatever_options_it_is_given(
    tmp_path: Path,
) -> None:
    for options in (None, ToolsOptions(purge_batch=5)):
        managers = build_managers(
            StorageMemoryImpl(), InfraLocalImpl(tmp_path), tools_options=options
        )
        # The engine's tools manager, beneath the layers the root puts on it.
        tools: object = managers.tools
        while hasattr(tools, "_inner"):
            tools = getattr(tools, "_inner")  # noqa: B009 (each layer's own field)
        ceilings = tools._options.ceilings  # pyright: ignore[reportAttributeAccessIssue]
        assert PROTECTED_CEILING in ceilings.rules
