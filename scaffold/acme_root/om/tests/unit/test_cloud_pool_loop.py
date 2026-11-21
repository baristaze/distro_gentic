"""A session of the cloud pool as the platform's loop runs it, over the VMs'
twin: its first model call waits for no VM. The VM starts at the first call
that reaches the workspace, and only that call waits for it; a run that
reaches none starts none. A spec the pool's VMs can never hold is refused
before any model call, and no VM starts: the kind's, and a session's pin
that asks more than its kind, its agent project's allowlist or workspace
base."""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from acme.infra.agent_workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
    ResourceLimits,
    VmSize,
)
from acme.infra.vms import VmSpec
from acme.infra.vms.twin import VmsTwinImpl
from acme.om.agent_projects.types.agent_project import AgentProjectWorkspaceBase
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopEndedHeader, LoopOutcome, ParkReason
from acme.om.agent_workspaces.rules import READ_ONLY
from acme.om.agent_workspaces.types.egress import EgressAllowlist, EgressRule
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.cloud_pool.impl.manager import CloudPoolOptions
from acme.om.cloud_pool.types.sizes import SIZES
from acme.om.platform_agents.kinds import SOFTWARE_ENGINEER
from acme.om.platform_loop_hooks import NEVER_HELD
from acme.om.platform_root import PlatformRootOptions

from contracts.agent_workspaces import AgentProjectsTwin
from contracts.loops import ASSISTANT, reply, said, use
from contracts.platform_loops import PlatformLoop, platform_loop_over

IMAGE = "acme-vm-image"
OPEN = IsolationSpec(mode=IsolationMode.VM, egress=EgressPolicy(mode=EgressMode.OPEN))
ON_A_VM = ASSISTANT.model_copy(update={"name": "on_a_vm", "isolation": OPEN})
MEDIUM = OPEN.model_copy(update={"limits": ResourceLimits(size=VmSize.M)})
ON_A_MEDIUM_VM = ASSISTANT.model_copy(update={"name": "on_a_medium_vm", "isolation": MEDIUM})
NO_MEDIUM = SIZES.model_copy(update={"m": None})
"""A deployment that maps no machine to `m`."""
BUILDS_ON_A_VM = ASSISTANT.model_copy(
    update={"name": SOFTWARE_ENGINEER, "version": 8, "isolation": OPEN}
)
"""A kind whose pin takes its agent project's workspace base."""


async def pooled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    agent_projects: AgentProjectsTwin | None = None,
) -> tuple[PlatformLoop, list[int]]:
    """A loop whose sessions of a VM run on the cloud pool, and the count of
    model calls made as each of its VMs started. No host enrolls, so a VM's
    workspace is refused for now, and the loop waits on the resource. Its
    sessions belong to `agent_projects`' one, when a case passes it."""
    loop = platform_loop_over(
        tmp_path,
        kinds=(ON_A_VM, ON_A_MEDIUM_VM, BUILDS_ON_A_VM),
        platform=PlatformRootOptions(
            workspace_agent_projects=agent_projects,
            cloud_pool_options=CloudPoolOptions(
                image=IMAGE,
                api_url="http://gateway.test",
                sizes=NO_MEDIUM,
                ready_wait=timedelta(milliseconds=50),
                first_poll=timedelta(milliseconds=5),
                last_poll=timedelta(milliseconds=10),
            ),
        ),
    )
    vms = loop.infra.get_vms()
    assert isinstance(vms, VmsTwinImpl)
    # The pool's image: a stopped VM that holds the host program.
    await vms.launch(IMAGE, VmSpec(image="twin", egress_open=True))
    await vms.stop(IMAGE)
    started: list[int] = []
    launch = vms.launch

    async def counted(name: str, spec: VmSpec, *args: Any, **kwargs: Any) -> None:
        started.append(len(loop.anthropic.calls))
        await launch(name, spec, *args, **kwargs)

    monkeypatch.setattr(vms, "launch", counted)
    return loop, started


async def test_a_session_of_the_cloud_pool_calls_its_model_before_its_vm_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, started = await pooled(tmp_path, monkeypatch)
    agent_session_id = await loop.start(ON_A_VM.name)

    # A run that reaches no workspace starts no VM.
    await loop.say(agent_session_id, "What is the plan?")
    loop.anthropic.add(reply(said("Read the logs, then fix the import.")))
    answered = await loop.loops.run(loop.owner, agent_session_id)

    assert answered.outcome is LoopOutcome.SUCCEEDED
    assert started == [], "no VM for a run that reaches no workspace"

    # Its first call that reaches the workspace starts the VM, after the
    # model call that asked for it, and waits for it alone.
    await loop.say(agent_session_id, "Fix it.")
    loop.anthropic.add(reply(use("lookup")))
    waiting = await loop.loops.run(loop.owner, agent_session_id)

    assert started == [2], "the VM started after the model call that reached it"
    assert waiting.end is RunEnd.PARKED and waiting.park is not None
    assert waiting.park.reason is ParkReason.LEASABLE_RESOURCE, "it waits for the VM's host"
    steps = await loop.history(agent_session_id)
    assert [step.type for step in steps][-2:] == [AgentStepType.TOOL_REQUEST, AgentStepType.PARKED]


async def test_a_spec_the_pool_never_holds_is_refused_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, started = await pooled(tmp_path, monkeypatch)
    agent_session_id = await loop.start(ON_A_MEDIUM_VM.name)
    await loop.say(agent_session_id, "Fix it.")
    loop.anthropic.add(reply(use("lookup")))

    run = await loop.loops.run(loop.owner, agent_session_id)

    assert (run.end, run.outcome) == (RunEnd.ENDED, LoopOutcome.ERRORED)
    assert loop.anthropic.calls == [], "refused before any model call"
    assert started == [], "no VM started"
    (ended,) = [
        s for s in await loop.history(agent_session_id) if s.type is AgentStepType.LOOP_ENDED
    ]
    assert isinstance(ended.header, LoopEndedHeader)
    assert ended.header.cause == "the cloud pool runs no VM of size m here"


@pytest.mark.parametrize(
    ("asks", "cause"),
    [
        ("allowlist", "a vm workspace cannot hold egress to allowlist"),
        ("base", "a session of the cloud pool starts from the pool's image, never from a base"),
    ],
    ids=["its agent project's allowlist", "its agent project's workspace base"],
)
async def test_a_pin_the_pool_never_holds_ends_the_loop_before_any_model_call_naming_its_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    asks: str,
    cause: str,
) -> None:
    """A kind the pool holds, pinned to more than its kind in its agent
    project: an allowlist's egress, which no VM holds, or a workspace base,
    which no VM starts from. The pin is held before the first model call,
    and the loop ends errored with no call spent and no VM started, its end
    naming the cause for a person."""
    agent_projects = AgentProjectsTwin(repository=None)
    loop, started = await pooled(tmp_path, monkeypatch, agent_projects)
    if asks == "allowlist":
        kind = ON_A_VM
        listed = EgressAllowlist(
            id=new_id(),
            created_at=loop.clock(),
            updated_at=loop.clock(),
            created_by=loop.owner.user_id,
            updated_by=loop.owner.user_id,
            agent_project_id=agent_projects.agent_project_id,
            rules=(EgressRule(destination="registry.example.com", methods=READ_ONLY),),
        )
        await loop.platform.agent_workspaces.write_allowlist(loop.owner, listed)
    else:
        kind = BUILDS_ON_A_VM
        base = AgentProjectWorkspaceBase(image="python:3.14-slim")
        agent_projects.agent_workspace_base = base.base()
    agent_session_id = await loop.start(kind.name)
    await loop.say(agent_session_id, "Fix it.")
    loop.anthropic.add(reply(use("lookup")))

    with caplog.at_level(logging.WARNING):
        run = await loop.loops.run(loop.owner, agent_session_id)

    assert (run.end, run.outcome) == (RunEnd.ENDED, LoopOutcome.ERRORED)
    assert loop.anthropic.calls == [], "refused before any model call"
    assert started == [], "no VM started"
    assert any(cause in record.getMessage() for record in caplog.records), "the log's"
    ended = (await loop.history(agent_session_id))[-1]
    assert ended.type is AgentStepType.LOOP_ENDED and isinstance(ended.header, LoopEndedHeader)
    assert ended.header.cause == f"{NEVER_HELD}: {cause}", "the person's"
