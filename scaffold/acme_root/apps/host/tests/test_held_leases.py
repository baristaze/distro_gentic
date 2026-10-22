"""A host keeps the leases it holds while its work takes long. An `exec`
item's lease is renewed from its claim, so a detail whose read outlasts
the lease, as one that carries a large write does on a slow link, never
lets it lapse. A large snapshot of a container workspace is scanned for
the host's secrets, hashed, and archived off the host's event loop, so
the host's heartbeat and the renewal of every other item it runs land on
time while it is taken. A snapshot that holds a secret's value, in any
form redaction matches, is refused and keeps nothing; one that holds none
is kept, and reads back to the digest and the size it was answered by.

The platform is faked on the wire and Docker on its command line; the
host's executor, its container provider, its snapshot store, and its
secret store are the ones a host runs."""

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import random
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import IO, Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx
import pytest

from acme.apps.host import main as host_main
from acme.apps.host.agent import HostAgent
from acme.apps.host.ceilings import Ask
from acme.apps.host.config import Settings
from acme.apps.host.exec_relay import EXEC, WORKSPACE, ExecutorRelayImpl
from acme.apps.host.snapshots import HostSnapshots, SnapshotLost
from acme.client.client import ApiClient
from acme.client.types.hosts import ClaimedWorkView
from acme.client.types.hosts import IsolationMode as HostMode
from acme.infra.agent_workspaces import (
    AgentWorkspace,
    Durability,
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationSpec,
)
from acme.infra.agent_workspaces.container import (
    AgentWorkspaceContainerImpl,
    _opened,
    container_name,
)
from acme.infra.agent_workspaces.twin import AgentWorkspaceTwinImpl
from acme.infra.docker import DockerReply
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.twin import TransportTwinImpl
from acme.om.base import new_id

TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))
KEPT = IsolationSpec(
    mode=IsolationMode.CONTAINER,
    egress=EgressPolicy(mode=EgressMode.NONE),
    durability=Durability.SNAPSHOT,
)
RENEW = 0.2
"""How often the host renews a lease here: a third of the lease."""
LEASE = RENEW * 3
ON_TIME = 1.0
"""How late past its schedule a renewal or a beat may land."""
DEPLOYMENT = "acme-test"
IMAGE_ID = "sha256:" + "0" * 64
MIB = 1 << 20


def asked(kind: str, isolation: HostMode | None) -> Ask:
    """What an item of `kind` at `isolation`, with no egress, asks."""
    return Ask(
        kind=kind,
        operation="snapshot" if kind == WORKSPACE else None,
        agent_project_id=None,
        isolation=isolation,
        egress=frozenset(),
        reads=(),
        by_person=False,
    )


class Platform:
    """The platform's side of the wire, recorded. It holds each `exec`
    item's lease to its term, as the sweep would: a renewal or a result
    that comes once the lease ran out is refused. An item's detail is
    answered once `read` is set. It records when each renewal landed and
    when the detail's read ended, each result, and each answer to a
    workspace item."""

    def __init__(self) -> None:
        self.details: dict[str, dict[str, Any]] = {}
        self.held_until: dict[str, float] = {}
        self.read = asyncio.Event()
        self.read.set()
        self.read_ended: float | None = None
        self.renewed: list[float] = []
        self.results: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any]] = []

    def client(self) -> ApiClient:
        return ApiClient(
            "http://platform.test",
            app="cli",
            app_version="test",
            token="host",
            transport=httpx.MockTransport(self._answer),
        )

    def claimed(self) -> ClaimedWorkView:
        """An `exec` item on the twin, claimed now: a command that exits 0."""
        item_id, agent_session_id, org_id = new_id(), new_id(), new_id()
        self.details[str(item_id)] = {
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
        self.held_until[str(item_id)] = time.monotonic() + LEASE
        return ClaimedWorkView(
            attempts=1,
            id=new_id(),
            kind=EXEC,
            lease_expires_at=None,
            org_id=org_id,
            payload={"item_id": str(item_id)},
            target_id=item_id,
            wire_version=1,
        )

    async def _answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/v1/hosts/me/workspaces/"):
            self.answers.append(json.loads(request.content))
            return httpx.Response(200, json={})
        item, _, call = path.removeprefix("/v1/hosts/me/exec/").partition("/")
        if not call:
            await self.read.wait()
            self.read_ended = time.monotonic()
            return httpx.Response(200, json=self.details[item])
        if time.monotonic() > self.held_until[item]:
            refused = {"code": "item_not_held", "message": "its lease ran out"}
            return httpx.Response(409, json={"error": refused})
        if call == "lease":
            self.held_until[item] = time.monotonic() + LEASE
            self.renewed.append(time.monotonic())
            return httpx.Response(200, json={"lease_expires_at": datetime.now(UTC).isoformat()})
        data = json.loads(request.content)["data"]
        self.results.append(json.loads(base64.b64decode(data)))
        return httpx.Response(200, json={})


class HeldPrepare(AgentWorkspaceTwinImpl):
    """The twin, its prepare held until `go` is set: an item that runs on
    while a snapshot is taken."""

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


def tar_of(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as written:
        for name, data in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            written.addfile(member, io.BytesIO(data))
    return out.getvalue()


class Docker:
    """Docker, faked, holding one running container of the session's, as
    this provider starts it: a copy of its volume prints `files`, and its
    writable layer changed `/opt/x` alone, which its export streams beside
    the image's own files. A stream is read in a thread, as Docker's own
    output is."""

    def __init__(self, org_id: UUID, agent_session_id: UUID, files: bytes) -> None:
        self.held = f"{container_name(agent_session_id)} {agent_session_id} {org_id}\n"
        self.runs = f"true {IMAGE_ID} {DEPLOYMENT} {agent_session_id} {org_id}\n"
        self.files = files
        self.export = tar_of({"opt/x": b"changed", "usr/lib/image.so": b"the image's"})

    async def __call__(self, *args: str, **_: object) -> DockerReply:
        if args[0] == "ps":
            return DockerReply(0, self.held.encode(), b"")
        if args[0] == "inspect":
            return DockerReply(0, self.runs.encode(), b"")
        if args[:2] == ("image", "inspect"):
            return DockerReply(0, b"[]", b"")
        if args[0] == "diff":
            return DockerReply(0, b"A /opt/x\n", b"")
        if args[0] == "cp":
            return DockerReply(0, self.files, b"")
        return DockerReply(0, b"", b"")  # pause, unpause

    async def stream[T](
        self, *args: str, bound: timedelta, read: Callable[[IO[bytes]], T]
    ) -> tuple[DockerReply, T | None]:
        streamed = self.export if args[0] == "export" else self.files
        return DockerReply(0, b"", b""), await asyncio.to_thread(read, io.BytesIO(streamed))


async def host_of(
    platform: Platform,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: bytes,
    secrets: dict[str, str],
) -> tuple[ExecutorRelayImpl, ClaimedWorkView, HostSnapshots, HeldPrepare]:
    """A host that runs container workspaces, kept by snapshots in its own
    store, and twin ones, whose prepare is held; its secret store holds
    `secrets` for the tenant. Answered with a snapshot item of a session's
    workspace whose volume holds `files`."""
    org_id, agent_session_id = new_id(), new_id()
    store = SecretsLocalImpl(tmp_path / "secrets")
    for name, value in secrets.items():
        await store.put(org_id, name, value)
    docker = Docker(org_id, agent_session_id, files)
    monkeypatch.setattr("acme.infra.agent_workspaces.container.docker", docker)
    monkeypatch.setattr("acme.infra.agent_workspaces.container.docker_stream", docker.stream)
    snapshots = HostSnapshots(tmp_path / "snapshots", tmp_path / "secrets")
    twin = HeldPrepare()
    executor = ExecutorRelayImpl(
        platform.client,
        {IsolationMode.TWIN: TransportTwinImpl(SecretsLocalImpl(None), BrokerNullImpl())},
        {
            IsolationMode.TWIN: twin,
            IsolationMode.CONTAINER: AgentWorkspaceContainerImpl(
                "python:3.14-slim", timedelta(seconds=30), DEPLOYMENT
            ),
        },
        snapshots=snapshots,
        snapshot_modes=lambda: frozenset({IsolationMode.CONTAINER}),
        renew_seconds=RENEW,
    )
    item = ClaimedWorkView(
        attempts=1,
        id=new_id(),
        kind=WORKSPACE,
        lease_expires_at=None,
        org_id=org_id,
        payload={
            "operation": "snapshot",
            "spec": KEPT.model_dump(mode="json"),
            "agent_session_id": str(agent_session_id),
            "snapshot": {"id": str(new_id())},
        },
        target_id=agent_session_id,
        wire_version=1,
    )
    return executor, item, snapshots, twin


# Check 1: a detail whose read outlasts the lease never lets it lapse.


async def test_an_exec_items_lease_is_renewed_from_its_claim_while_its_detail_is_read() -> None:
    platform = Platform()
    executor = ExecutorRelayImpl(
        platform.client,
        {IsolationMode.TWIN: TransportTwinImpl(SecretsLocalImpl(None), BrokerNullImpl())},
        {IsolationMode.TWIN: AgentWorkspaceTwinImpl()},
        renew_seconds=RENEW,
    )
    item = platform.claimed()
    platform.read.clear()

    run = asyncio.ensure_future(executor.run(item, asked(EXEC, None)))
    await asyncio.sleep(LEASE * 2.5)  # the read outlasts the lease
    platform.read.set()
    await asyncio.wait_for(run, 5)

    assert platform.read_ended is not None
    assert [at for at in platform.renewed if at < platform.read_ended], "renewed while read"
    assert [result["outcome"]["exit_code"] for result in platform.results] == [0]


# Check 2: a large snapshot holds up no other lease the host holds.

SNAPSHOT_BYTES = 512 * MIB
SECRETS = 10


async def test_a_large_snapshot_holds_up_neither_the_heartbeat_nor_another_items_renewal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = {f"TOKEN_{n}": f"tok-{n}-{random.randbytes(16).hex()}" for n in range(SECRETS)}
    platform = Platform()
    executor, snapshot, _, twin = await host_of(
        platform, tmp_path, monkeypatch, random.randbytes(SNAPSHOT_BYTES), secrets
    )
    beats: list[float] = []

    class Beating:
        async def rotate_if_due(self) -> bool:
            return False

        async def beat(self) -> None:
            beats.append(time.monotonic())

    settings = Settings(
        api_url="http://test",
        home=tmp_path,
        name="host-1",
        enrollment_token=None,
        workspace_user=None,
        beat_seconds=RENEW,
    )
    beating = asyncio.ensure_future(host_main.keep_alive(cast(HostAgent, Beating()), settings))
    running = asyncio.ensure_future(executor.run(platform.claimed(), asked(EXEC, None)))
    await asyncio.sleep(RENEW * 3)

    began = time.monotonic()
    await executor.run(snapshot, asked(WORKSPACE, HostMode.container))
    ended = time.monotonic()
    await asyncio.sleep(RENEW * 3)
    twin.go.set()
    await asyncio.wait_for(running, 5)
    beating.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await beating

    assert set(platform.answers[0]) == {"reference", "digest", "size"}
    assert platform.answers[0]["size"] > SNAPSHOT_BYTES
    for name, ticks in (("heartbeat", beats), ("renewal", platform.renewed)):
        waited = longest_wait(ticks, began, ended)
        assert waited <= RENEW + ON_TIME, (name, round(ended - began, 2), round(waited, 2))
    assert [result["outcome"]["exit_code"] for result in platform.results] == [0]


def longest_wait(ticks: list[float], began: float, ended: float) -> float:
    """The longest wait between two of `ticks` while a snapshot was taken,
    from `began` to `ended`: from the last tick before it to the first one
    after it, or to its end when none came after."""
    before = max(at for at in ticks if at <= began)
    after = min((at for at in ticks if at >= ended), default=ended)
    marks = [before, *(at for at in ticks if before < at < after), after]
    return max(later - earlier for earlier, later in pairwise(marks))


# Check 3: a snapshot that holds a secret's value, in any form, keeps nothing.

SECRET = 'tok-3f9A/b+c="q"\\9z'


def written(value: str) -> dict[str, str]:
    """The ways a program writes a value to a file by accident."""
    raw = value.encode()
    return {
        "raw": value,
        "base64": base64.b64encode(raw).decode(),
        "base64 unpadded": base64.b64encode(raw).decode().rstrip("="),
        "base64 url": base64.urlsafe_b64encode(raw).decode(),
        "base64 inside a longer run": base64.b64encode(b"Authorization: Basic " + raw).decode(),
        "base64 at an odd offset": base64.b64encode(b"x" + raw + b"y").decode(),
        "hex": raw.hex(),
        "hex upper": raw.hex().upper(),
        "url escaped": quote(value, safe=""),
        "json escaped": json.dumps({"token": value}),
        "repr": repr(value),
    }


@pytest.mark.parametrize("how", list(written(SECRET)))
async def test_a_snapshot_that_holds_a_secrets_value_in_any_form_is_refused_and_keeps_nothing(
    how: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    noise = random.randbytes(3 * MIB)
    files = noise[: 2 * MIB] + written(SECRET)[how].encode() + noise[2 * MIB :]
    platform = Platform()
    executor, snapshot, _, _ = await host_of(
        platform, tmp_path, monkeypatch, files, {"SERVICE_TOKEN": SECRET}
    )

    await executor.run(snapshot, asked(WORKSPACE, HostMode.container))

    [answer] = platform.answers
    assert "SERVICE_TOKEN" in answer["refused"] and SECRET not in answer["refused"]
    assert not any(path.is_file() for path in (tmp_path / "snapshots").rglob("*"))


# Check 4: a snapshot reads back to its digest and its size.


async def test_a_kept_snapshot_reads_back_whole_to_its_digest_and_its_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = tar_of({"workspace/data.bin": random.randbytes(3 * MIB)})
    platform = Platform()
    executor, snapshot, snapshots, _ = await host_of(
        platform, tmp_path, monkeypatch, files, {"SERVICE_TOKEN": SECRET}
    )

    await executor.run(snapshot, asked(WORKSPACE, HostMode.container))

    [answer] = platform.answers
    kept = (tmp_path / "snapshots" / answer["reference"]).read_bytes()
    assert answer["size"] == len(kept)
    assert answer["digest"] == "sha256:" + hashlib.sha256(kept).hexdigest()
    loaded = await snapshots.load(answer["reference"], answer["digest"], answer["size"])
    opened = _opened(loaded)
    assert (opened.image, opened.pull, opened.deleted) == (IMAGE_ID, None, ())
    assert opened.files == files
    with tarfile.open(fileobj=io.BytesIO(opened.layer)) as layer:
        assert layer.getnames() == ["opt/x"]
    altered = bytearray(kept)
    altered[len(altered) // 2] ^= 1
    (tmp_path / "snapshots" / answer["reference"]).write_bytes(bytes(altered))
    with pytest.raises(SnapshotLost):
        await snapshots.load(answer["reference"], answer["digest"], answer["size"])
