"""A session of the cloud pool as the platform's loop runs it, over the VMs'
twin: its first model call waits for no VM. The VM starts at the first call
that reaches the workspace, and only that call waits for it; a run that
reaches none starts none. A spec the pool's VMs can never hold is refused
before any model call, and no VM starts."""

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
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopEndedHeader, LoopOutcome, ParkReason
from acme.om.agents.types.run import RunEnd
from acme.om.cloud_pool.impl.manager import CloudPoolOptions
from acme.om.cloud_pool.types.sizes import SIZES
from acme.om.platform_root import PlatformRootOptions

from contracts.loops import ASSISTANT, reply, said, use
from contracts.platform_loops import PlatformLoop, platform_loop_over

IMAGE = "acme-vm-image"
OPEN = IsolationSpec(mode=IsolationMode.VM, egress=EgressPolicy(mode=EgressMode.OPEN))
ON_A_VM = ASSISTANT.model_copy(update={"name": "on_a_vm", "isolation": OPEN})
MEDIUM = OPEN.model_copy(update={"limits": ResourceLimits(size=VmSize.M)})
ON_A_MEDIUM_VM = ASSISTANT.model_copy(update={"name": "on_a_medium_vm", "isolation": MEDIUM})
NO_MEDIUM = SIZES.model_copy(update={"m": None})
"""A deployment that maps no machine to `m`."""


async def pooled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[PlatformLoop, list[int]]:
    """A loop whose sessions of a VM run on the cloud pool, and the count of
    model calls made as each of its VMs started. No host enrolls, so a VM's
    workspace is refused for now, and the loop waits on the resource."""
    loop = platform_loop_over(
        tmp_path,
        kinds=(ON_A_VM, ON_A_MEDIUM_VM),
        platform=PlatformRootOptions(
            cloud_pool_options=CloudPoolOptions(
                image=IMAGE,
                api_url="http://gateway.test",
                sizes=NO_MEDIUM,
                ready_wait=timedelta(milliseconds=50),
                first_poll=timedelta(milliseconds=5),
                last_poll=timedelta(milliseconds=10),
            )
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
