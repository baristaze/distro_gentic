"""A session kept by snapshots, end to end on the local stack: its sessions,
history, and records in Postgres, its snapshots on the stack's MinIO, and a
container per workspace on Docker. Its loop writes files and installs a
package outside the workspace's volume; the loop ends, its run snapshots
the container, and the workspace is released. The runner restarts: a new
root over the same storage, the same buckets, and the same key service,
with nothing of the first in memory, and the workspace's volume gone. The
session's next loop finds the same tree, by hash, and the package there.

Skipped, with the reason, where no Docker runs. Needs a migrated database
(`make migrate`)."""

import json
import secrets as tokens
import shlex
import subprocess
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import aioboto3
import pytest

from acme.infra.agent_workspaces import (
    AgentWorkspaceProviderInterface,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.container import AgentWorkspaceContainerImpl, container_name
from acme.infra.buckets import Buckets, BucketsInterface
from acme.infra.buckets.s3 import BucketsS3Impl
from acme.infra.docker import docker
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.local import InfraLocalImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.keys import KeyServiceInterface
from acme.infra.transports import TransportInterface
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.container import TransportContainerImpl
from acme.om.agent_steps.types.agent_step import AgentStep, AgentStepType
from acme.om.agent_steps.types.content import TextBlock
from acme.om.agent_steps.types.header import LoopOutcome, SnapshotHeader
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.platform_root import build_platform_managers
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.tools.impl.snapshots import BUCKET, session_prefix
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import ToolClass

from contracts.loops import ALLOWED, ASSISTANT, call, reply, said
from contracts.platform_loops import PlatformLoop, platform_loop_over
from contracts.tools import Command

IMAGE = "python:3.14-slim"
APP = AppContext(type=AppType.PORTAL, version="portal@test")
KEPT = IsolationSpec(
    mode=IsolationMode.CONTAINER,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
KEEPER = ASSISTANT.model_copy(
    update={
        "name": "keeper",
        "isolation": KEPT,
        "tools": (*ASSISTANT.tools, "run_command"),
        "policy": ToolPolicyLayer(
            rules=(
                *ALLOWED.rules,
                ToolPolicyRule(authorization_class=ToolClass.EXECUTE, decision=Decision.ALLOW),
            )
        ),
    }
)

# A wheel built by hand inside the workspace, installed with no network into
# the image's site-packages, outside the workspace's volume.
BUILD = """
import zipfile
files = {
    "tool/__init__.py": "VERSION = '1.0'\\n",
    "tool-1.0.dist-info/METADATA": "Metadata-Version: 2.1\\nName: tool\\nVersion: 1.0\\n",
    "tool-1.0.dist-info/WHEEL": (
        "Wheel-Version: 1.0\\nGenerator: hand\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n"
    ),
}
files["tool-1.0.dist-info/RECORD"] = "".join(f"{name},,\\n" for name in files) + (
    "tool-1.0.dist-info/RECORD,,\\n"
)
with zipfile.ZipFile("/workspace/tool-1.0-py3-none-any.whl", "w") as wheel:
    for name, text in files.items():
        wheel.writestr(name, text)
"""
SITE = "/usr/local/lib/python3.14/site-packages/tool"
WORK = (
    "mkdir -p /workspace/notes && echo 'what the loop learned' > /workspace/notes/today.md"
    f" && python -c {shlex.quote(BUILD)}"
    " && pip install --no-index --no-deps --quiet /workspace/tool-1.0-py3-none-any.whl"
)
TREE = (
    f"find /workspace {SITE} -type f -not -name '*.pyc' -exec sha256sum {{}} + | sort | sha256sum"
    " && python -c 'import tool; print(tool.VERSION)'"
)


def docker_runs() -> bool:
    try:
        reply = subprocess.run(["docker", "version"], capture_output=True, timeout=20)
    except FileNotFoundError, subprocess.TimeoutExpired:
        return False
    return reply.returncode == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not docker_runs(), reason="needs a local Docker"),
]


class OnDocker(InfraLocalImpl):
    """The local root with a container per workspace, its transport, the
    stack's MinIO, and the key service the case shares between roots, as a
    deployment's processes share one."""

    def __init__(
        self, root: Path, buckets: BucketsInterface, keys: KeyServiceInterface | None
    ) -> None:
        super().__init__(root)
        if keys is not None:
            self._keys = keys
        self.workspaces = AgentWorkspaceContainerImpl(IMAGE, timedelta(seconds=300), "acme-test")
        self.transport = TransportContainerImpl(
            root / "records", self.get_secrets(), BrokerNullImpl(), timedelta(seconds=120)
        )
        self.buckets = buckets

    def get_agent_workspaces(self) -> AgentWorkspaceProviderInterface:
        return self.workspaces

    def get_transport(self) -> TransportInterface:
        return self.transport

    def get_buckets(self) -> BucketsInterface:
        return self.buckets


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


@pytest.fixture
async def minio() -> AsyncIterator[BucketsS3Impl]:
    """The S3 impl over the stack's MinIO, on a snapshots bucket of its own,
    emptied and removed afterwards."""
    settings = InfraSettings()
    session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key or "acme",
        aws_secret_access_key=settings.s3_secret_key or "acme-minio-local",
        region_name=settings.aws_region,
    )
    endpoint = settings.s3_endpoint_url or "http://127.0.0.1:59000"
    prefix = f"acme-it-{tokens.token_hex(4)}"
    name = f"{prefix}-{Buckets.SNAPSHOTS.value}"
    admin: Any = session.client("s3", endpoint_url=endpoint)
    async with admin as s3:
        await s3.create_bucket(Bucket=name)
    impl = BucketsS3Impl(
        session,
        endpoint_url=endpoint,
        region=settings.aws_region,
        bucket_prefix=prefix,
        timeout=timedelta(seconds=30),
    )
    await impl.start()
    try:
        yield impl
    finally:
        await impl.close()
        cleanup: Any = session.client("s3", endpoint_url=endpoint)
        async with cleanup as s3:
            listed = await s3.list_objects_v2(Bucket=name)
            for item in listed.get("Contents", []):
                await s3.delete_object(Bucket=name, Key=item["Key"])
            await s3.delete_bucket(Bucket=name)


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_platform_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


def a_runner(
    root: Path,
    storage: StoragePostgresImpl,
    owner: TenantContext,
    buckets: BucketsInterface,
    keys: KeyServiceInterface | None = None,
) -> tuple[PlatformLoop, OnDocker]:
    """A runner's root, as one process builds it as it starts."""
    root.mkdir(parents=True, exist_ok=True)
    infra = OnDocker(root, buckets, keys)
    loop = platform_loop_over(
        root,
        kinds=(ASSISTANT, KEEPER),
        storage=storage,
        owner=owner,
        infra=infra,
        extra=(Command("run_command"),),
    )
    return loop, infra


def printed(history: list[AgentStep]) -> str:
    """What the last command the loop ran printed."""
    last = [step for step in history if step.type is AgentStepType.TOOL_RESPONSE][-1]
    (part,) = last.as_tool_response().parts
    assert isinstance(part, TextBlock)
    return json.loads(part.text)["stdout"]


async def test_a_kept_session_resumes_on_the_tree_it_left_after_the_runner_restarts(
    storage: StoragePostgresImpl, minio: BucketsS3Impl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    first, infra = a_runner(tmp_path / "first", storage, owner, minio)
    agent_session_id = await first.start(KEEPER.name)
    try:
        await first.say(agent_session_id, "Note what you learned and install the tool.")
        first.anthropic.add(
            reply(call("run_command", argv=["sh", "-c", WORK])),
            reply(call("run_command", argv=["sh", "-c", TREE])),
            reply(said("Noted and installed.")),
        )
        ran = await first.loops.run(owner, agent_session_id)
        assert ran.outcome is LoopOutcome.SUCCEEDED
        history = await first.history(agent_session_id)
        left = printed(history)
        assert left.endswith("1.0\n"), left
        (taken,) = [step for step in history if step.type is AgentStepType.SNAPSHOTTED]
        assert isinstance(taken.header, SnapshotHeader)
        named = taken.header.snapshot
        stored = await minio.list(owner.org_id, BUCKET, session_prefix(agent_session_id), 10)
        assert len(stored) == 1, "kept on MinIO"
        record = await first.platform.agent_workspaces.kept_snapshot(owner, named.id)
        assert record is not None and not record.on_host and record.hash == named.hash
        name = container_name(agent_session_id)
        shown = await docker("inspect", "--type", "container", name, bound=timedelta(seconds=20))
        assert not shown.ok, "released once its snapshot held it"

        # The runner restarts: nothing of the first root is held, and the
        # workspace's volume is gone with its VM.
        removed = await docker("volume", "rm", "-f", name, bound=timedelta(seconds=60))
        assert removed.ok
        second, _ = a_runner(tmp_path / "second", storage, owner, minio, infra.get_keys())
        await second.say(agent_session_id, "Is the tool still there?")
        second.anthropic.add(
            reply(call("run_command", argv=["sh", "-c", TREE])),
            reply(said("It is.")),
        )
        resumed = await second.loops.run(owner, agent_session_id)

        assert resumed.outcome is LoopOutcome.SUCCEEDED
        assert printed(await second.history(agent_session_id)) == left, "the same tree, by hash"
    finally:
        await first.managers.tools.purge_agent_workspace(owner.org_id, agent_session_id)
