"""A prepare that runs longer than the work's claim, as the first one on a
fresh host whose image takes minutes to pull. Nothing renews a workspace
item's claim, so a prepare whose image is still being pulled is answered
with a refusal that clears, the pull runs on, and a later claim finds the
image: the image is pulled once, and no prepare runs twice. An `exec`
item's lease is renewed from before its workspace is prepared, so a
prepare that blocks never lets it lapse."""

import asyncio
import base64
import contextlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from acme.apps.host import main as host_main
from acme.apps.host.ceilings import Ask
from acme.apps.host.config import Settings
from acme.apps.host.exec_relay import EXEC, WORKSPACE, ExecutorRelayImpl
from acme.client.client import ApiClient
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    AgentWorkspace,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.container import container_name
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.docker import DockerReply
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.twin import TransportTwinImpl
from acme.om.base import new_id

SEALED = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))
TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))


def asked(kind: str, isolation: HostMode | None) -> Ask:
    """What an item of `kind` at `isolation`, with no egress, asks."""
    return Ask(
        kind=kind,
        operation="prepare" if kind == WORKSPACE else None,
        agent_project_id=None,
        isolation=isolation,
        egress=frozenset(),
        reads=(),
        by_person=False,
    )


class SlowPull:
    """Docker, faked: the image is absent until its pull ends, and a pull
    waits on `release`. No container is found, and every other command
    succeeds. `pulls` counts the pulls started."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.pulled = asyncio.Event()
        self.pulls = 0

    async def __call__(self, *args: str, **_: object) -> DockerReply:
        if args[0] == "pull":
            self.pulls += 1
            await self.release.wait()
            self.pulled.set()
        elif args[:2] == ("image", "inspect") and not self.pulled.is_set():
            return DockerReply(1, b"", b"Error: No such image")
        elif args[0] == "inspect":
            return DockerReply(1, b"", b"Error: No such object")
        return DockerReply(0, b"", b"")


class Platform:
    """The platform's side of the wire, recorded: each prepare's answer as
    the host sent it, each lease renewal, and each result. An `exec` item's
    detail is `detail`. `extended` is set at the first renewal."""

    def __init__(self, detail: dict[str, Any] | None = None) -> None:
        self.detail = detail
        self.answers: list[dict[str, Any]] = []
        self.extends = 0
        self.extended = asyncio.Event()
        self.results: list[dict[str, Any]] = []

    def client(self) -> ApiClient:
        return ApiClient(
            "http://platform.test",
            app="cli",
            app_version="test",
            token="host",
            transport=httpx.MockTransport(self._answer),
        )

    def _answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v1/hosts/me/workspaces/"):
            self.answers.append(json.loads(request.content))
            return httpx.Response(200, json={"held": True})
        if path.endswith("/lease"):
            self.extends += 1
            self.extended.set()
            return httpx.Response(200, json={"lease_expires_at": datetime.now(UTC).isoformat()})
        if path.endswith("/result"):
            data = json.loads(request.content)["data"]
            self.results.append(json.loads(base64.b64decode(data)))
            return httpx.Response(200, json={})
        return httpx.Response(200, json=self.detail)


def prepare_of(agent_session_id: UUID, spec: IsolationSpec) -> ClaimedWorkView:
    """A workspace item that asks the host to prepare the session's
    workspace to `spec`."""
    return ClaimedWorkView(
        attempts=1,
        id=new_id(),
        kind=WORKSPACE,
        lease_expires_at=None,
        org_id=new_id(),
        payload={
            "operation": "prepare",
            "spec": spec.model_dump(mode="json"),
            "agent_session_id": str(agent_session_id),
        },
        target_id=agent_session_id,
        wire_version=1,
    )


async def test_a_prepare_whose_image_is_still_pulled_is_refused_until_its_one_pull_ends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = SlowPull()
    monkeypatch.setattr("acme.infra.agent_workspaces.container.docker", docker)
    monkeypatch.setattr(host_main, "PULL_WAIT", timedelta(0))
    settings = Settings(
        api_url="http://test",
        home=tmp_path,
        name="host-1",
        enrollment_token=None,
        workspace_user=None,
    )
    platform = Platform()
    executor = ExecutorRelayImpl(platform.client, {}, host_main.host_workspaces(settings))
    agent_session_id = new_id()
    item = prepare_of(agent_session_id, SEALED)
    ask = asked(WORKSPACE, HostMode.container)

    # Answered while the pull still runs: a refusal neither lost nor
    # unbuilt, which the platform defers, so the claim never runs out.
    await asyncio.wait_for(executor.run(item, ask), 5)
    assert not docker.pulled.is_set()
    pulling = f"this host is pulling the image {settings.agent_workspace_image}"
    assert platform.answers == [{"refused": pulling, "lost": False, "unbuilt": False}]

    docker.release.set()
    await asyncio.wait_for(docker.pulled.wait(), 5)
    await asyncio.wait_for(executor.run(item, ask), 5)
    assert platform.answers[1:] == [{"location": container_name(agent_session_id)}]
    assert docker.pulls == 1


class HeldPrepare(AgentWorkspaceTwinImpl):
    """The twin, its prepare held until `go` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.go = asyncio.Event()

    async def prepare(
        self,
        org_id: UUID,
        agent_workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> AgentWorkspace:
        await self.go.wait()
        return await super().prepare(
            org_id, agent_workspace_id, spec, snapshot, base, building=building
        )


async def test_an_exec_items_lease_is_renewed_while_its_workspace_is_prepared() -> None:
    item_id, agent_session_id, org_id = new_id(), new_id(), new_id()
    platform = Platform(
        detail={
            "agent_session_id": str(agent_session_id),
            "call_id": str(new_id()),
            "deadline": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "effect": "read_only",
            "epoch": 1,
            "item_id": str(item_id),
            "location": f"twin:{agent_session_id.hex}",
            "org_id": str(org_id),
            "request": {"operation": "run", "argv": ["true"]},
            "spec": TWIN.model_dump(mode="json"),
        }
    )
    workspaces = HeldPrepare()
    transport = TransportTwinImpl(SecretsLocalImpl(None), BrokerNullImpl())
    executor = ExecutorRelayImpl(
        platform.client,
        {IsolationMode.TWIN: transport},
        {IsolationMode.TWIN: workspaces},
        renew_seconds=0,
    )
    item = ClaimedWorkView(
        attempts=1,
        id=new_id(),
        kind=EXEC,
        lease_expires_at=None,
        org_id=org_id,
        payload={"item_id": str(item_id)},
        target_id=item_id,
        wire_version=1,
    )

    run = asyncio.ensure_future(executor.run(item, asked(EXEC, None)))
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(platform.extended.wait(), 1)
    renewed = platform.extends  # while the prepare is still held
    workspaces.go.set()
    await asyncio.wait_for(run, 5)

    assert renewed >= 1
    assert [result["outcome"]["exit_code"] for result in platform.results] == [0]
