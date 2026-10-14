"""The cloud pool end to end, on Lima: a session of the cloud whose kind
runs in a VM, over Postgres, as the session runner runs it, and the host
program inside the session's own machine, which reaches the API over the
network, as a machine of the cloud reaches the gateway.

The session's first loop starts a machine from the pool's image; its host
trades the key it was handed for a credential of the session's pool of one,
prepares the workspace, and runs the session's command there: a Docker
image built and a container run of it. The loop's end keeps the machine
whole: the host's credential ends, the machine stops, and its disk is kept
as the session's snapshot; then the machine goes. The next loop starts a
machine from that snapshot, whose new host finds the same file and the same
image. The host's environment holds nothing of the platform's.

Needs a migrated database (`make migrate`), Lima and a hypervisor, and the
pool's image, which it builds when it is missing
(`deployment/machines/lima_image.py`). Every machine it starts is named
under `ACME_MACHINE_PREFIX` and destroyed at the end; the image stays for
the next run."""

import asyncio
import os
import re
import shutil
import subprocess
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import uvicorn
from host_support import Stack, postgres, stack
from runner_support import TOOLS, answers, assistant, runs

from acme.infra.machines import MachineState
from acme.infra.machines.lima import MachinesLimaImpl, hypervisor
from acme.infra.machines.seeded import SeedsChannelImpl
from acme.infra.workspaces import Durability, EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.types.request import Start
from acme.om.base import new_id, utcnow
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import LoopOutcome
from acme.om.steps.types.step import StepType
from acme.services.api.app import create_app
from acme.services.api.seed import seed_platform
from acme.workers.session_runner.container import RunnerContainer
from acme.workers.session_runner.settings import SessionRunnerSettings

PREFIX = os.environ.get("ACME_MACHINE_PREFIX", "acme-test-")
IMAGE = f"{PREFIX}image"
PORT = int(os.environ.get("ACME_TEST_API_PORT", "8191"))
KEPT = IsolationSpec(
    mode=IsolationMode.VM,
    egress=EgressPolicy(mode=EgressMode.OPEN),
    durability=Durability.SNAPSHOT,
)
KIND = assistant(KEPT)
TIMEOUT = timedelta(minutes=2)
BOOT = timedelta(minutes=15)

BUILD = (
    "mkdir -p ctx && "
    "echo state-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \\n') > ctx/state.txt && "
    "printf 'FROM busybox:1.37\\nCOPY state.txt /state.txt\\n' > ctx/Dockerfile && "
    "docker build -q -t acme-pool-kept ctx >/dev/null && "
    "cat ctx/state.txt && docker run --rm acme-pool-kept cat /state.txt"
)
"""What the first loop's command does: a file, a Docker image built on it,
and a container run of it, which prints the file's line twice."""

FOUND = (
    "cat ctx/state.txt && docker run --rm acme-pool-kept cat /state.txt && "
    "echo @ENVIRONMENT@ && "
    "tr '\\0' '\\n' < /proc/$(systemctl show -p MainPID --value acme-host)/environ "
    "| cut -d= -f1 && echo @SEED@ && cat /run/acme-machine/seed.json && echo @END@"
)
"""What the next loop's command reads: the file and the image the first one
made, the names in the host program's environment, as its process holds
them, and the machine's seed, which its commands can read too."""

NOTHING_OF_THE_PLATFORMS = re.compile(
    r"DATABASE|POSTGRES|VALKEY|S3_|AWS_|KMS|SECRET|PASSWORD|ANTHROPIC|OPENAI|GEMINI|"
    r"MODEL|PROVIDER|LAUNCHDARKLY|SENTRY|ENROLLMENT_TOKEN"
)


def lima_runs() -> bool:
    return shutil.which("limactl") is not None and hypervisor() is None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not lima_runs(), reason="needs Lima and a hypervisor"),
]


@pytest.fixture(scope="module")
def image() -> str:
    """The pool's image, built from this checkout when it is missing."""
    root = Path(__file__).resolve().parents[3]
    built = subprocess.run(
        ["uv", "run", "python", "deployment/machines/lima_image.py", IMAGE],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=BOOT.total_seconds(),
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return IMAGE


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    """The API over Postgres, served on this host's loopback, which a Lima
    guest reaches as `host.lima.internal`."""
    storage = postgres()
    async with stack(tmp_path / "api", storage) as running:
        config = uvicorn.Config(
            create_app(running.container),
            host="127.0.0.1",
            port=PORT,
            lifespan="off",
            log_level="warning",
        )
        server = uvicorn.Server(config)
        serving = asyncio.ensure_future(server.serve())
        for _ in range(400):
            if server.started:
                break
            await asyncio.sleep(0.05)
        try:
            yield running
        finally:
            server.should_exit = True
            await serving
    await storage.close()


@pytest.fixture
def machines() -> MachinesLimaImpl:
    return MachinesLimaImpl(TIMEOUT, BOOT, encrypted=True)


@pytest.fixture
async def runner(
    api: Stack, image: str, machines: MachinesLimaImpl
) -> AsyncIterator[RunnerContainer]:
    infra = api.container.infra
    # The runner's machines are Lima's: its pool starts them, and hands each
    # its seed through the hypervisor's channel.
    infra._machines = machines  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    infra._seeds = SeedsChannelImpl(machines, TIMEOUT)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    settings = SessionRunnerSettings.model_validate(
        {
            "_env_file": None,
            "environment": "test",
            "runner_id": "runner-pool",
            "machine_prefix": PREFIX,
            "machine_boot_timeout_seconds": BOOT.total_seconds(),
            "cloud_pool_image": image,
            "cloud_pool_api_url": f"http://host.lima.internal:{PORT}",
        }
    )
    container = RunnerContainer.over(
        settings,
        postgres(),
        infra,
        IntegrationsOverImpl(IdentityProviderAbsentImpl(), scripted_model_providers()),
        ports=PlatformPorts(kinds=ProductKinds(agents=(KIND,), tools=lambda _: TOOLS)),
    )
    yield container
    await container.managers.cloud_pool.close()
    await container.storage.close()


def printed(model: ModelProviderScriptedImpl, call: int) -> str:
    """What the command printed, as the model read it on a call."""
    return repr(model.calls[call])


async def test_a_session_of_the_cloud_pool_keeps_its_whole_machine_across_loops(
    api: Stack, runner: RunnerContainer, machines: MachinesLimaImpl
) -> None:
    owner = api.owner
    managers = runner.managers
    pool = managers.cloud_pool
    await seed_platform(runner.storage, managers, owner, (KIND,))
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    session = await managers.agents.start_session(
        owner, Start(id=new_id(), kind=KIND.name, title="a machine of its own")
    )
    try:
        # The first loop: a machine from the pool's image, its host, and a
        # command that builds an image and runs a container of it.
        said = message_step(new_id(), utcnow(), session.id, owner, "Build it.")
        await managers.agent_sessions.receive(owner, session.id, [said])
        model.add(runs("sh", "-c", BUILD))
        model.add(answers("Built."))
        first = await managers.loop.run(owner, session.id)
        assert first.outcome is LoopOutcome.SUCCEEDED, first
        state = printed(model, 1)
        digest = re.search(r"(state-[0-9a-f]{32})", state)
        assert digest is not None, state
        assert state.count(digest.group(1)) >= 2, "the file, and the container's copy of it"

        # The loop's end kept the machine whole, and let it go.
        page = await managers.steps.get_steps(owner, session.id, 0, 200)
        snapshotted = [s for s in page.items if s.type is StepType.SNAPSHOTTED]
        assert len(snapshotted) == 1
        (record,) = await managers.agent_workspaces.kept_snapshots(owner, session.id)
        assert record.machine and record.reference.startswith(PREFIX + "p")
        assert await machines.state(record.reference) is MachineState.STOPPED
        assert not await pool.holds(owner, session.id), "the machine went with the release"
        running = [n for n in await machines.names(PREFIX + "p") if "-" not in n[len(PREFIX) :]]
        assert running == [], "no machine of the pool runs between loops"

        # The next loop: a machine from the snapshot, a new host, the same
        # file and the same image.
        again = message_step(new_id(), utcnow(), session.id, owner, "Is it there?")
        await managers.agent_sessions.receive(owner, session.id, [again])
        model.add(runs("sh", "-c", FOUND))
        model.add(answers("It is."))
        second = await managers.loop.run(owner, session.id)
        if second.park is not None and second.park.unlock == "approval":
            # The session read what its first command printed, and its
            # egress is open: a person approves the call, and the loop goes
            # on, on a machine started from the snapshot its park kept.
            page = await managers.steps.get_steps(owner, session.id, 0, 200)
            requests = [s for s in page.items if s.type is StepType.TOOL_REQUEST]
            await managers.tools.decide_call(owner, session.id, requests[-1].seq, approve=True)
            second = await managers.loop.run(owner, session.id)
        assert second.outcome is LoopOutcome.SUCCEEDED, second
        found = printed(model, len(model.calls) - 1)
        assert found.count(digest.group(1)) >= 2, found

        # The machine's host holds nothing of the platform's, and its key is
        # spent and gone from the seed.
        # What it printed follows the command's own text in the call.
        environment = found.rsplit("@ENVIRONMENT@", 1)[1].split("@SEED@", 1)[0]
        seed = found.rsplit("@SEED@", 1)[1].split("@END@", 1)[0]
        assert "ACME_HOST_MACHINE_SEED" in environment, environment
        assert not NOTHING_OF_THE_PLATFORMS.search(environment), environment
        assert "api_url" in seed and "hmk_" not in seed, seed
    finally:
        await pool.purge(owner.org_id, session.id)
    assert await machines.names(PREFIX + "p") == [], "every machine and disk of the session"
