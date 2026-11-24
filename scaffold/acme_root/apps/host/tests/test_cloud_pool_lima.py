"""The cloud pool end to end, on Lima: a session of the cloud whose kind
runs in a VM, over Postgres, as the session runner runs it, and the host
program inside the session's own VM, which reaches the API over the
network, as a VM of the cloud reaches the gateway.

The session's first loop starts a VM from the pool's image; its host
trades the key it was handed for a credential of the session's pool of one,
prepares the workspace, and runs the session's command there: a Docker
image built and a container run of it. The loop's end keeps the
workspace's directory: packed in the VM and read out through the relay,
each part sealed under the session's key in the bucket; then the VM
goes, and no disk of it is kept. The next loop's VM boots the pool's
image, and its new host takes the directory back: the same file, and
no Docker image, which lived outside it. Each VM is a claim counted once,
whose wait ends at its first command, and the restore is timed. The
host's environment holds nothing of the platform's. Every part of the
directory crosses the store, as a command's output past what rides in
its result does, here the local impl's, served on this host's loopback
beside the API, which the guest reaches the same way.

Needs a migrated database (`make migrate`), Lima and a hypervisor, and the
pool's image, which it builds when it is missing
(`deployment/vms/lima_image.py`). Every VM it starts is named
under `ACME_VM_PREFIX` and destroyed at the end; the image stays for
the next run."""

import asyncio
import os
import re
import shutil
import subprocess
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from host_support import Stack, postgres, stack
from prometheus_client import REGISTRY
from runner_support import TOOLS, answers, assistant, runs

from acme.infra.agent_workspaces import (
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.buckets import Buckets
from acme.infra.buckets.local import BucketsLocalImpl
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.platform_root import PlatformInfra
from acme.infra.vms.lima import VmsLimaImpl, hypervisor
from acme.infra.vms.seeded import SeedsChannelImpl
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import LoopOutcome
from acme.om.agents.types.request import Start
from acme.om.base import new_id, utcnow
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.om.tools.impl.snapshots import session_prefix, snapshot_key
from acme.services.api.app import create_app
from acme.services.api.seed import seed_platform
from acme.workers.agent_session_runner.container import RunnerContainer
from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

PREFIX = os.environ.get("ACME_VM_PREFIX", "acme-test-")
IMAGE = f"{PREFIX}image"
PORT = int(os.environ.get("ACME_TEST_API_PORT", "8191"))
STORE_PORT = int(os.environ.get("ACME_TEST_STORE_PORT", str(PORT + 1)))
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
    "cat ctx/state.txt && "
    "echo images-$(docker images -q acme-pool-kept | wc -l | tr -d ' ') && "
    "echo @ENVIRONMENT@ && "
    "tr '\\0' '\\n' < /proc/$(systemctl show -p MainPID --value acme-host)/environ "
    "| cut -d= -f1 && echo @SEED@ && cat /run/acme-vm/seed.json && echo @END@"
)
"""What the next loop's command reads: the file the first one made, how
many Docker images of it the new VM holds, the names in the host
program's environment, as its process holds them, and the VM's seed,
which its commands can read too."""

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
        ["uv", "run", "python", "deployment/vms/lima_image.py", IMAGE],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=BOOT.total_seconds(),
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return IMAGE


async def served(app: Any, port: int) -> tuple[uvicorn.Server, asyncio.Future[None]]:
    """`app` served on this host's loopback at `port`, once it listens."""
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        lifespan="off",
        log_level="warning",
        interface="asgi3",
    )
    server = uvicorn.Server(config)
    serving = asyncio.ensure_future(server.serve())
    for _ in range(400):
        if server.started:
            break
        await asyncio.sleep(0.05)
    return server, serving


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Stack]:
    """The API over Postgres, and the local store, each served on this
    host's loopback, which a Lima guest reaches as `host.lima.internal`:
    the store signs its URLs for that name."""
    storage = postgres()
    infra = InfraLocalImpl(tmp_path / "infra")
    buckets = BucketsLocalImpl(
        tmp_path / "infra" / "buckets", url=f"http://host.lima.internal:{STORE_PORT}"
    )
    infra._buckets = buckets  # pyright: ignore[reportPrivateUsage]
    async with stack(tmp_path / "api", storage, infra) as running:
        servers = [
            await served(create_app(running.container), PORT),
            await served(buckets.store, STORE_PORT),
        ]
        try:
            yield running
        finally:
            for server, serving in servers:
                server.should_exit = True
                await serving
    await storage.close()


@pytest.fixture
def vms() -> VmsLimaImpl:
    return VmsLimaImpl(TIMEOUT, BOOT, encrypted=True)


@pytest.fixture
async def runner(api: Stack, image: str, vms: VmsLimaImpl) -> AsyncIterator[RunnerContainer]:
    infra = api.container.infra
    # The runner's VMs are Lima's: its pool starts them, and hands each
    # its seed through the hypervisor's channel.
    infra._agent_infra = replace(infra._agent_infra, vms=vms)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    infra._platform_infra = PlatformInfra(  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
        infra.get_streams(), SeedsChannelImpl(vms, TIMEOUT)
    )
    settings = AgentSessionRunnerSettings.model_validate(
        {
            "_env_file": None,
            "environment": "test",
            "runner_id": "runner-pool",
            "vm_prefix": PREFIX,
            "vm_boot_timeout_seconds": BOOT.total_seconds(),
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


def sampled(name: str) -> float:
    """A metric's value the process holds, every label together."""
    return sum(
        sample.value
        for metric in REGISTRY.collect()
        for sample in metric.samples
        if sample.name == name
    )


def printed(model: ModelProviderScriptedImpl, call: int) -> str:
    """What the command printed, as the model read it on a call."""
    return repr(model.calls[call])


async def test_a_session_of_the_cloud_pool_keeps_its_files_sealed_across_loops(
    api: Stack, runner: RunnerContainer, vms: VmsLimaImpl
) -> None:
    owner = api.owner
    managers = runner.managers
    pool = managers.cloud_pool
    await seed_platform(runner.storage, managers, owner, (KIND,))
    model = runner.integrations.get_model_providers().get(ProviderName.ANTHROPIC)
    assert isinstance(model, ModelProviderScriptedImpl)
    session = await managers.agents.start_agent_session(
        owner, Start(id=new_id(), kind=KIND.name, title="a VM of its own")
    )
    claims = sampled("acme_cloud_pool_claims_total")
    waits = sampled("acme_cloud_pool_first_command_seconds_count")
    restores = sampled("acme_cloud_pool_restore_seconds_count")
    try:
        # The first loop: a VM from the pool's image, its host, and a
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
        assert sampled("acme_cloud_pool_claims_total") == claims + 1, "one claim, a new VM"
        assert sampled("acme_cloud_pool_first_command_seconds_count") == waits + 1, (
            "its wait ends at the first of its commands, through the runner's transport"
        )

        # The loop's end kept the directory in sealed parts, and let the
        # VM go with no disk kept.
        page = await managers.agent_steps.get_agent_steps(owner, session.id, 0, 200)
        snapshotted = [s for s in page.items if s.type is AgentStepType.SNAPSHOTTED]
        assert len(snapshotted) == 1
        (record,) = await managers.agent_workspaces.kept_snapshots(owner, session.id)
        assert not record.on_host
        assert record.reference == snapshot_key(session.id, record.hash)
        parts = await api.container.infra.get_buckets().list(
            owner.org_id, Buckets.SNAPSHOTS, f"{session_prefix(session.id)}workspace/", 100
        )
        assert parts, "the directory in parts"
        assert not await pool.holds(owner, session.id), "the VM went with the release"
        assert await vms.names(PREFIX + "p") == [], "no VM, and no disk of one, between loops"

        # The next loop: a VM from the pool's image, a new host, the same
        # file, and no image built outside the directory.
        again = message_step(new_id(), utcnow(), session.id, owner, "Is it there?")
        await managers.agent_sessions.receive(owner, session.id, [again])
        model.add(runs("sh", "-c", FOUND))
        model.add(answers("It is."))
        second = await managers.loop.run(owner, session.id)
        if second.park is not None and second.park.unlock == "approval":
            # The session read what its first command printed, and its
            # egress is open: a person approves the call, and the loop goes
            # on, on a VM started from the snapshot its park kept.
            page = await managers.agent_steps.get_agent_steps(owner, session.id, 0, 200)
            requests = [s for s in page.items if s.type is AgentStepType.TOOL_REQUEST]
            await managers.tools.decide_call(owner, session.id, requests[-1].seq, approve=True)
            second = await managers.loop.run(owner, session.id)
        assert second.outcome is LoopOutcome.SUCCEEDED, second
        found = printed(model, len(model.calls) - 1)
        assert digest.group(1) in found, found
        assert "images-0" in found, "what lived outside the directory is the image's again"
        claimed = sampled("acme_cloud_pool_claims_total") - claims
        assert sampled("acme_cloud_pool_first_command_seconds_count") - waits == claimed, (
            "each claim's wait, once"
        )
        assert sampled("acme_cloud_pool_restore_seconds_count") > restores, "the restore, timed"

        # The VM's host holds nothing of the platform's, and its key is
        # spent and gone from the seed.
        # What it printed follows the command's own text in the call.
        environment = found.rsplit("@ENVIRONMENT@", 1)[1].split("@SEED@", 1)[0]
        seed = found.rsplit("@SEED@", 1)[1].split("@END@", 1)[0]
        assert "ACME_HOST_VM_SEED" in environment, environment
        assert not NOTHING_OF_THE_PLATFORMS.search(environment), environment
        assert "api_url" in seed and "hmk_" not in seed, seed
    finally:
        await pool.purge(owner.org_id, session.id)
    assert await vms.names(PREFIX + "p") == [], "every VM of the session"
