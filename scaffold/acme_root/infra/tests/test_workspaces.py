"""Isolation is chosen up front and never weakened. A provider meets a spec
whole or refuses it, before it creates anything, and never hands back a
weaker place: not the host directory for a container, and not a container
with open egress for one that asked for none. A container holds the host's
CA file, read-only, under open egress alone. A host directory's release ends
what its commands left running there.

An account workspace runs its commands as an account of the host, which the
cases that need one name in TEST_WORKSPACE_ACCOUNT. They are skipped, with
the reason, on a host that cannot switch to it: one not on Linux, or a
process without the capabilities the switch takes, as in most CI. Their
root's filesystem keeps ACLs. One more runs under a unit with
`ProcSubset=pid` and `RestrictSUIDSGID=yes` alone, and is skipped, with the
reason, anywhere else."""

import asyncio
import contextlib
import io
import os
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from acme.infra.base import new_id, utcnow
from acme.infra.docker import DockerReply
from acme.infra.docker import docker as docker_cli
from acme.infra.exceptions import BackendFailed
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CommandResult, CommandSpec
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.local import TransportLocalImpl
from acme.infra.transports.twin import RecordSealTwin
from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    HeldInstance,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    ResourceLimits,
    Workspace,
    WorkspaceProviderInterface,
)
from acme.infra.workspaces import account as accounts
from acme.infra.workspaces.account import Switch, WorkspaceAccountImpl, switch_to
from acme.infra.workspaces.container import (
    CA_PATH,
    DOCKER_PROXIES,
    ICC,
    OPEN_NETWORK,
    WorkspaceContainerImpl,
    container_name,
)
from acme.infra.workspaces.host import WorkspaceHostImpl
from acme.infra.workspaces.network import CAFileUnreadable, HostNetwork
from acme.infra.workspaces.twin import WorkspaceNullImpl, WorkspaceTwinImpl

DEPLOYMENT = "acme-test"
"""The deployment the providers of these cases start their containers for."""

NONE = EgressPolicy(mode=EgressMode.NONE)
OPEN = EgressPolicy(mode=EgressMode.OPEN)
ALLOWLIST = EgressPolicy(mode=EgressMode.ALLOWLIST, hosts=("pypi.org",))


def spec(mode: IsolationMode, egress: EgressPolicy = OPEN, **limits: float) -> IsolationSpec:
    return IsolationSpec(mode=mode, egress=egress, limits=ResourceLimits.model_validate(limits))


HOST_REFUSES = [
    spec(IsolationMode.VM),
    spec(IsolationMode.CONTAINER),
    spec(IsolationMode.ACCOUNT),
    spec(IsolationMode.TWIN),
    spec(IsolationMode.HOST, NONE),
    spec(IsolationMode.HOST, ALLOWLIST),
    spec(IsolationMode.HOST, memory_mb=512),
    spec(IsolationMode.HOST, processes=64),
    spec(IsolationMode.HOST, cpus=1),
]

CONTAINER_REFUSES = [
    spec(IsolationMode.VM, NONE),
    spec(IsolationMode.HOST),
    spec(IsolationMode.TWIN, NONE),
    spec(IsolationMode.CONTAINER, ALLOWLIST),
]


@pytest.mark.parametrize("asked", HOST_REFUSES, ids=lambda s: s.model_dump_json())
async def test_a_host_directory_refuses_what_it_cannot_hold_and_makes_nothing(
    tmp_path: Path, asked: IsolationSpec
) -> None:
    root = tmp_path / "workspaces"
    with pytest.raises(IsolationRefused):
        await WorkspaceHostImpl(root).prepare(new_id(), new_id(), asked)
    assert not root.exists(), "nothing is made for a spec that is refused"


async def test_a_host_directory_meets_the_host_mode_and_keeps_its_files_past_a_release(
    tmp_path: Path,
) -> None:
    provider = WorkspaceHostImpl(tmp_path)
    org, workspace_id = new_id(), new_id()
    workspace = await provider.prepare(org, workspace_id, spec(IsolationMode.HOST))
    (Path(workspace.location) / "notes.txt").write_text("kept")
    await provider.release(workspace)
    again = await provider.prepare(org, workspace_id, spec(IsolationMode.HOST))
    assert (Path(again.location) / "notes.txt").read_text() == "kept"
    await provider.purge(org, workspace_id)
    assert not await asyncio.to_thread(Path(again.location).exists)


async def left_behind(cwd: Path) -> int:
    """A process a command left running in `cwd` as one does: put in the
    background with its output sent elsewhere, by a shell that then ended,
    so nothing waits on it. Its id."""
    shell = await asyncio.create_subprocess_exec(
        "sh",
        "-c",
        "sleep 300 >/dev/null 2>&1 & echo $!",
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    out, _ = await shell.communicate()
    return int(out)


async def running(pid: int) -> bool:
    """Whether `pid` still runs, given a few seconds to be gone."""
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        await asyncio.sleep(0.1)
    return True


def kill_quietly(*pids: int) -> None:
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


async def test_a_host_release_ends_what_its_commands_left_running_and_nothing_else(
    tmp_path: Path,
) -> None:
    """Its instance is what runs in it: a release ends each process whose
    directory is inside the workspace, one of this process's own children
    among them, and leaves one elsewhere alone."""
    provider = WorkspaceHostImpl(tmp_path / "workspaces")
    workspace = await provider.prepare(new_id(), new_id(), spec(IsolationMode.HOST))
    nested = Path(workspace.location) / "server"
    nested.mkdir()
    left, deeper = await left_behind(Path(workspace.location)), await left_behind(nested)
    elsewhere = await left_behind(tmp_path)
    child = await asyncio.create_subprocess_exec(
        "sleep", "300", cwd=workspace.location, start_new_session=True
    )
    try:
        await provider.release(workspace)
        assert not await running(left) and not await running(deeper)
        assert await asyncio.wait_for(child.wait(), 10) < 0, "ended by a signal"
        os.kill(elsewhere, 0)  # still there
    finally:
        kill_quietly(left, deeper, elsewhere)
        if child.returncode is None:
            child.kill()
            await child.wait()


def left_locked(location: Path, outside: Path) -> None:
    """What commands leave in a workspace: a module cache read-only, as `go
    mod download` leaves its own, a directory no one may read, and a link
    to a directory outside the workspace."""
    cache = location / "go" / "pkg" / "mod" / "m@v1"
    cache.mkdir(parents=True)
    (cache / "go.mod").write_text("module m\n")
    cache.chmod(0o555)
    cache.parent.chmod(0o555)
    hidden = location / "hidden"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("x")
    hidden.chmod(0)
    outside.mkdir()
    outside.chmod(0o555)
    (location / "elsewhere").symlink_to(outside)


async def test_a_host_purge_removes_what_a_command_left_locked_and_follows_no_link(
    tmp_path: Path,
) -> None:
    provider = WorkspaceHostImpl(tmp_path / "workspaces")
    workspace = await provider.prepare(new_id(), new_id(), spec(IsolationMode.HOST))
    outside = tmp_path / "outside"
    await asyncio.to_thread(left_locked, Path(workspace.location), outside)
    try:
        await provider.purge(workspace.org_id, workspace.id)
        assert not await asyncio.to_thread(Path(workspace.location).exists)
        assert (await asyncio.to_thread(outside.stat)).st_mode & 0o777 == 0o555, "not followed"
    finally:
        await asyncio.to_thread(outside.chmod, 0o755)


async def test_a_host_purge_ends_what_runs_there_before_its_files_go(tmp_path: Path) -> None:
    provider = WorkspaceHostImpl(tmp_path / "workspaces")
    workspace = await provider.prepare(new_id(), new_id(), spec(IsolationMode.HOST))
    left = await left_behind(Path(workspace.location))
    try:
        await provider.purge(workspace.org_id, workspace.id)
        assert not await running(left)
        assert not await asyncio.to_thread(Path(workspace.location).exists)
    finally:
        kill_quietly(left)


@pytest.mark.parametrize("asked", CONTAINER_REFUSES, ids=lambda s: s.model_dump_json())
async def test_a_container_provider_refuses_what_it_cannot_hold_before_it_reaches_docker(
    monkeypatch: pytest.MonkeyPatch, asked: IsolationSpec
) -> None:
    calls: list[tuple[str, ...]] = []

    async def docker(*args: str, **_: object) -> object:
        calls.append(args)
        raise AssertionError("a refused spec reaches no docker")

    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    with pytest.raises(IsolationRefused):
        await provider.prepare(new_id(), new_id(), asked)
    assert calls == []


class LocalDocker:
    """Docker, faked for one container: `create` makes it with the labels
    it names, `rm` removes it, and `inspect` renders its format over it as
    Docker does. A network stands once made, with the options it was made
    with. It keeps every command it is given, and what each was fed on its
    input."""

    def __init__(self) -> None:
        self.labels: dict[str, str] | None = None  # the running container's, when one runs
        self.networks: dict[str, dict[str, str]] = {}  # each network's options, by name
        self.calls: list[tuple[str, ...]] = []
        self.bounds: dict[str, timedelta] = {}  # the limit each command ran under
        self.fed: dict[str, object] = {}  # the input each command was given
        self.image_present = True

    async def __call__(self, *args: str, **kwargs: object) -> DockerReply:
        self.calls.append(args)
        self.bounds[args[0]] = kwargs["bound"]  # type: ignore[assignment]
        self.fed[args[0]] = kwargs.get("stdin")
        if args[:2] == ("image", "inspect") and not self.image_present:
            return DockerReply(1, b"", b"Error: No such image")
        if args[0] == "pull":
            self.image_present = True
        if args[:2] == ("network", "create"):
            pairs = [args[i + 1] for i, arg in enumerate(args) if arg == "--opt"]
            self.networks[args[-1]] = dict(pair.split("=", 1) for pair in pairs)
        elif args[:2] == ("network", "inspect"):
            options = self.networks.get(args[-1])
            if options is None:
                return DockerReply(1, b"", b"Error: No such network")
            wanted = re.search(r'"([^"]+)"', args[args.index("--format") + 1])
            assert wanted is not None
            return DockerReply(0, f"{options.get(wanted.group(1), '<no value>')}\n".encode(), b"")
        elif args[0] == "create":
            pairs = [args[i + 1] for i, arg in enumerate(args) if arg == "--label"]
            self.labels = dict(pair.split("=", 1) for pair in pairs)
        elif args[0] == "rm":
            self.labels = None
        elif args[0] == "inspect":
            if self.labels is None:
                return DockerReply(1, b"", b"Error: No such object")
            labels = self.labels
            rendered = re.sub(
                r'\{\{index \.Config\.Labels "([^"]+)"\}\}',
                lambda found: labels.get(found.group(1), "<no value>"),
                args[args.index("--format") + 1].replace("{{.State.Running}}", "true"),
            )
            return DockerReply(0, f"{rendered}\n".encode(), b"")
        return DockerReply(0, b"", b"")


STARTED_AGAIN = ["version", "inspect", "rm", "image", "volume", "create", "start"]
"""What a prepare runs when the container it finds is not the one its spec
asks for, and the host has no CA file to copy in."""


async def test_a_running_container_is_reused_only_under_the_spec_it_was_started_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session whose spec was tightened since its container started, from
    open egress to none, never gets that container back: it is replaced,
    and its files, in their volume, are kept."""
    opened, closed = spec(IsolationMode.CONTAINER, OPEN), spec(IsolationMode.CONTAINER, NONE)
    docker = LocalDocker()
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    org, workspace_id = new_id(), new_id()
    await provider.prepare(org, workspace_id, opened)
    docker.calls.clear()
    await provider.prepare(org, workspace_id, opened)
    assert [call[0] for call in docker.calls] == ["version", "inspect"], "the same spec reuses it"
    docker.calls.clear()
    await provider.prepare(org, workspace_id, closed)
    assert [call[0] for call in docker.calls] == STARTED_AGAIN
    created = docker.calls[-2]
    assert created[created.index("--network") + 1] == "none", "it holds the tighter spec"
    assert not any(call[:2] == ("volume", "rm") for call in docker.calls), "its files stay"
    assert docker.labels is not None and docker.labels["acme.deployment"] == DEPLOYMENT

    # One started without this deployment's label, as before it was
    # written, is replaced too, and the new one carries it.
    del docker.labels["acme.deployment"]
    docker.calls.clear()
    await provider.prepare(org, workspace_id, closed)
    assert [call[0] for call in docker.calls] == STARTED_AGAIN
    assert docker.labels["acme.deployment"] == DEPLOYMENT
    volume = docker.calls[-3]
    assert f"acme.deployment={DEPLOYMENT}" in volume, "its volume carries it as well"


async def test_a_container_holds_a_copy_of_the_hosts_ca_under_open_egress_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container with open egress is given a copy of the host's CA file,
    as the host read it when it started, before it starts; one with no
    egress holds nothing of the host's. Docker is never asked to reach the
    host's path, so a path its daemon cannot see costs no prepare, and a
    file gone since the host started costs none either. One started
    without the CA, as before the host named one, is replaced, its files
    kept, so no command is pointed at a file its container lacks."""
    real = tmp_path / "certs" / "host-ca.pem"
    real.parent.mkdir()
    real.write_bytes(b"the host's own")
    ca = tmp_path / "linked-ca.pem"
    ca.symlink_to(real)
    docker = LocalDocker()
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    bare = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    networked = WorkspaceContainerImpl(
        "python:3.14-slim",
        timedelta(seconds=5),
        DEPLOYMENT,
        network=HostNetwork.of({"SSL_CERT_FILE": str(ca)}),
    )
    real.unlink()
    org, workspace_id = new_id(), new_id()
    await bare.prepare(org, workspace_id, spec(IsolationMode.CONTAINER, OPEN))
    docker.calls.clear()
    await networked.prepare(org, workspace_id, spec(IsolationMode.CONTAINER, OPEN))
    name = container_name(workspace_id)
    # Open egress finds its bridge, which the bare prepare made, before the create.
    assert [call[0] for call in docker.calls] == [
        *STARTED_AGAIN[:-2],
        "network",
        "create",
        "cp",
        "start",
    ]
    assert docker.calls[-2] == ("cp", "-", f"{name}:/")
    fed = docker.fed["cp"]
    assert isinstance(fed, bytes)
    with tarfile.open(fileobj=io.BytesIO(fed)) as archive:
        (entry,) = archive.getmembers()
        copied = archive.extractfile(entry)
        assert copied is not None and copied.read() == b"the host's own"
    assert "/" + entry.name == CA_PATH and entry.mode == 0o444, "readable by all, written by none"
    created = docker.calls[-3]
    assert "--mount" not in created and str(ca) not in " ".join(created)
    assert not any(call[:2] == ("volume", "rm") for call in docker.calls), "its files stay"

    docker.calls.clear()
    await networked.prepare(org, workspace_id, spec(IsolationMode.CONTAINER, OPEN))
    assert [call[0] for call in docker.calls] == ["version", "inspect"], "it is reused"

    docker.calls.clear()
    await networked.prepare(org, workspace_id, spec(IsolationMode.CONTAINER, NONE))
    assert [call[0] for call in docker.calls] == STARTED_AGAIN, "no egress, no copy"


@pytest.mark.parametrize("egress", [OPEN, NONE])
async def test_a_container_is_started_with_every_proxy_dockers_config_fills_left_unset(
    egress: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `docker` command line copies the proxies its config file names
    into every container it starts, credentials included, unless each is
    named: each is, with no value, so each is left unset."""
    docker = LocalDocker()
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    await provider.prepare(new_id(), new_id(), spec(IsolationMode.CONTAINER, egress))
    (created,) = (call for call in docker.calls if call[0] == "create")
    named = [created[i + 1] for i, flag in enumerate(created) if flag == "--env"]
    assert sorted(named) == sorted(DOCKER_PROXIES)
    assert {"HTTPS_PROXY", "https_proxy", "NO_PROXY", "ALL_PROXY", "FTP_PROXY"} <= set(named)


def test_a_ca_file_the_host_cannot_read_stops_it_as_it_starts(tmp_path: Path) -> None:
    """The CA file is read once, as the host starts: one it cannot read
    stops it there, never at a session's prepare."""
    for unreadable in (tmp_path / "absent.pem", tmp_path):
        with pytest.raises(CAFileUnreadable):
            HostNetwork.of({"SSL_CERT_FILE": str(unreadable)})


async def test_an_absent_image_is_pulled_under_the_pull_limit_before_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run's own limit is short, and a pull the run carried would be killed
    on a slow link, with its layers discarded: the image is pulled first, on
    a limit of its own, and only when it is absent."""
    docker = LocalDocker()
    docker.image_present = False
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl(
        "python:3.14-slim", timedelta(seconds=5), DEPLOYMENT, timedelta(seconds=900)
    )
    await provider.prepare(new_id(), new_id(), spec(IsolationMode.CONTAINER, NONE))
    names = [call[0] for call in docker.calls]
    assert names.index("pull") < names.index("create")
    assert ("pull", "python:3.14-slim") in docker.calls
    assert docker.bounds["pull"] == timedelta(seconds=900)
    assert docker.bounds["create"] == timedelta(seconds=5), "the create keeps its own limit"
    docker.calls.clear()
    await provider.prepare(new_id(), new_id(), spec(IsolationMode.CONTAINER, NONE))
    assert "pull" not in [call[0] for call in docker.calls], "a present image is not pulled"


async def test_open_egress_workspaces_share_a_bridge_where_none_reaches_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two workspaces with open egress never land on Docker's default
    bridge, where every container reaches every other: each joins the one
    bridge made with traffic between its containers off, made once."""
    docker = LocalDocker()
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    opened = spec(IsolationMode.CONTAINER, OPEN)

    await provider.prepare(new_id(), new_id(), opened)
    docker.labels = None  # the double holds one container: the second is another
    await provider.prepare(new_id(), new_id(), opened)

    creates = [call for call in docker.calls if call[0] == "create"]
    assert [call[call.index("--network") + 1] for call in creates] == [OPEN_NETWORK, OPEN_NETWORK]
    made = [call for call in docker.calls if call[:2] == ("network", "create")]
    assert len(made) == 1 and docker.networks == {OPEN_NETWORK: {ICC: "false"}}


async def test_a_bridge_that_lets_its_containers_reach_each_other_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network of that name made by anything else, with traffic between
    its containers on, is never joined: the workspace is refused and no
    container starts."""
    docker = LocalDocker()
    docker.networks[OPEN_NETWORK] = {ICC: "true"}
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)

    with pytest.raises(IsolationRefused, match="reach each other"):
        await provider.prepare(new_id(), new_id(), spec(IsolationMode.CONTAINER, OPEN))
    assert not any(call[0] in ("create", "start") for call in docker.calls)


async def test_a_container_purge_by_ids_removes_its_container_and_its_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A purge needs no workspace in hand: the container and its volume are
    named by the workspace's id. A Docker that cannot remove them fails the
    purge, so nothing is left behind as if it went."""
    docker = LocalDocker()
    monkeypatch.setattr("acme.infra.workspaces.container.docker", docker)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    workspace_id = new_id()
    name = container_name(workspace_id)
    await provider.purge(new_id(), workspace_id)
    assert docker.calls == [("rm", "-f", name), ("volume", "rm", "-f", name)]

    async def unreachable(*args: str, **_: object) -> DockerReply:
        return DockerReply(1, b"", b"Cannot connect to the Docker daemon")

    monkeypatch.setattr("acme.infra.workspaces.container.docker", unreachable)
    with pytest.raises(BackendFailed):
        await provider.purge(new_id(), workspace_id)


# What each provider holds: an instance prepared and not let go since,
# whichever process prepared it, and nothing it did not make.


async def test_a_host_holds_each_directory_from_its_prepare_to_its_release(
    tmp_path: Path,
) -> None:
    """The directory outlives its release, so a mark beside it, never in
    it, says it is held. Nothing else under the root is named: not the
    transport's records, and not a name that is no prepare's."""
    root = tmp_path / "workspaces"
    provider = WorkspaceHostImpl(root)
    org = new_id()
    first, second = [
        await provider.prepare(org, new_id(), spec(IsolationMode.HOST)) for _ in range(2)
    ]
    (root / ".records").mkdir()
    (root / org.hex / "not-an-id.held").touch()
    (root / org.hex / f"{new_id()}.held").touch()  # an id, though not as a prepare names it
    assert sorted(await provider.held(), key=lambda held: held.location) == sorted(
        (
            HeldInstance(id=place.id, org_id=org, location=place.location)
            for place in (first, second)
        ),
        key=lambda held: held.location,
    )
    assert await asyncio.to_thread(os.listdir, first.location) == [], "no mark in it"

    await provider.release(first)
    assert [held.id for held in await provider.held()] == [second.id]
    assert await asyncio.to_thread(Path(first.location).is_dir), "its files outlive the release"
    await provider.prepare(org, first.id, first.spec)
    await provider.purge(org, first.id)
    await provider.purge(org, second.id)
    assert await provider.held() == []


async def test_a_container_provider_holds_the_running_containers_it_started_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker lists the running containers that carry the workspace label;
    of those, only one named for the workspace its label names is held."""
    ours, org = new_id(), new_id()
    listing = "\n".join(
        (
            f"{container_name(ours)} {ours} {org}",
            f"labelled-by-hand {new_id()} {org}",
            f"{container_name(ours)} not-an-id {org}",
            f"{container_name(new_id())}  ",
        )
    )
    calls: list[tuple[str, ...]] = []

    async def listed(*args: str, **_: object) -> DockerReply:
        calls.append(args)
        return DockerReply(0, f"{listing}\n".encode(), b"")

    monkeypatch.setattr("acme.infra.workspaces.container.docker", listed)
    provider = WorkspaceContainerImpl("python:3.14-slim", timedelta(seconds=5), DEPLOYMENT)
    assert await provider.held() == [
        HeldInstance(id=ours, org_id=org, location=container_name(ours))
    ]
    (call,) = calls
    assert call[:3] == ("ps", "--filter", "label=acme.workspace"), "labelled ones alone"
    assert call[3:5] == ("--filter", f"label=acme.deployment={DEPLOYMENT}"), "its own deployment's"
    assert "-a" not in call and "--all" not in call, "running ones alone"

    async def unreachable(*args: str, **_: object) -> DockerReply:
        return DockerReply(1, b"", b"Cannot connect to the Docker daemon")

    monkeypatch.setattr("acme.infra.workspaces.container.docker", unreachable)
    with pytest.raises(BackendFailed):
        await provider.held()


def docker_runs() -> bool:
    try:
        reply = subprocess.run(["docker", "version"], capture_output=True, timeout=20)
    except FileNotFoundError, subprocess.TimeoutExpired:
        return False
    return reply.returncode == 0


@pytest.mark.integration
@pytest.mark.skipif(not docker_runs(), reason="needs a local Docker")
async def test_a_container_provider_never_holds_a_container_it_did_not_start() -> None:
    """On the local Docker: the container a prepare started is held until
    its release. A container started without the labels, and one another
    deployment started on the same Docker, are never held, and still run
    after the release."""
    bound = timedelta(seconds=300)
    provider = WorkspaceContainerImpl("python:3.14-slim", bound, f"ours-{new_id().hex}")
    theirs = WorkspaceContainerImpl("python:3.14-slim", bound, f"theirs-{new_id().hex}")
    org, other = new_id(), new_id()
    workspace = await provider.prepare(org, new_id(), spec(IsolationMode.CONTAINER, NONE))
    elsewhere = await theirs.prepare(other, new_id(), spec(IsolationMode.CONTAINER, NONE))
    bare = f"bare-{new_id().hex}"
    started = await docker_cli(
        "run", "--detach", "--name", bare, "python:3.14-slim", "sleep", "infinity", bound=bound
    )
    try:
        assert started.ok, started.reason()
        held = await provider.held()
        assert HeldInstance(id=workspace.id, org_id=org, location=workspace.location) in held
        assert bare not in {instance.location for instance in held}
        assert elsewhere.id not in {instance.id for instance in held}, "another deployment's"
        assert [instance.id for instance in await theirs.held()] == [elsewhere.id]
        await provider.release(workspace)
        assert workspace.id not in {instance.id for instance in await provider.held()}
        for name in (bare, elsewhere.location):
            running = await docker_cli(
                "inspect", "--format", "{{.State.Running}}", name, bound=bound
            )
            assert running.stdout.strip() == b"true", f"{name} is left alone"
    finally:
        await docker_cli("rm", "-f", bare, bound=bound)
        await provider.purge(org, workspace.id)
        await theirs.purge(other, elsewhere.id)


async def test_the_twin_holds_what_it_prepared_until_it_is_let_go() -> None:
    twin = WorkspaceTwinImpl()
    org = new_id()
    kept, let_go = [
        await twin.prepare(org, new_id(), spec(IsolationMode.TWIN, NONE)) for _ in range(2)
    ]
    await twin.release(let_go)
    assert await twin.held() == [HeldInstance(id=kept.id, org_id=org, location=kept.location)]
    assert await WorkspaceNullImpl().held() == []


async def test_a_container_spec_with_no_docker_is_refused_and_never_swapped_for_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The configured root picks the container backend; with no Docker to
    reach, the session's spec is refused, and no host directory is made in
    its place."""
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/no-docker.sock")
    root = tmp_path / "workspaces"
    infra = InfraConfiguredImpl(
        InfraSettings.model_validate(
            {
                "environment": "local",
                "secrets_file": tmp_path / "secrets.env",
                "workspace_backend": "container",
                "workspaces_root": root,
                "docker_timeout_seconds": 20,
            }
        )
    )
    with pytest.raises(IsolationRefused, match="needs Docker"):
        await infra.get_workspaces().prepare(
            new_id(), new_id(), spec(IsolationMode.CONTAINER, NONE)
        )
    assert not root.exists()


@pytest.mark.parametrize(
    "provider", [WorkspaceTwinImpl(), WorkspaceNullImpl()], ids=lambda p: p.describe()
)
async def test_the_twin_and_the_null_provider_refuse_every_mode_not_theirs(
    provider: WorkspaceProviderInterface,
) -> None:
    for mode in (
        IsolationMode.VM,
        IsolationMode.CONTAINER,
        IsolationMode.HOST,
        IsolationMode.ACCOUNT,
    ):
        with pytest.raises(IsolationRefused):
            await provider.prepare(new_id(), new_id(), spec(mode, NONE))
    if isinstance(provider, WorkspaceNullImpl):
        with pytest.raises(IsolationRefused):
            await provider.prepare(new_id(), new_id(), spec(IsolationMode.TWIN, NONE))
    else:
        twin = await provider.prepare(new_id(), new_id(), spec(IsolationMode.TWIN, NONE, cpus=1))
        assert twin.spec.limits.cpus == 1


def test_an_allowlist_names_its_hosts_and_no_other_egress_does() -> None:
    with pytest.raises(ValueError):
        EgressPolicy(mode=EgressMode.ALLOWLIST)
    with pytest.raises(ValueError):
        EgressPolicy(mode=EgressMode.OPEN, hosts=("pypi.org",))


def test_the_absent_workspace_is_the_none_mode() -> None:
    absent = Workspace.absent(new_id(), new_id())
    assert absent.spec.mode is IsolationMode.NONE and absent.location == ""


ACCOUNT = os.environ.get("TEST_WORKSPACE_ACCOUNT", "")

ACCOUNT_REFUSES = [
    spec(IsolationMode.HOST),
    spec(IsolationMode.CONTAINER),
    spec(IsolationMode.ACCOUNT, NONE),
    spec(IsolationMode.ACCOUNT, ALLOWLIST),
    spec(IsolationMode.ACCOUNT, memory_mb=512),
    spec(IsolationMode.ACCOUNT, cpus=1),
    spec(IsolationMode.ACCOUNT, processes=64, memory_mb=512),
]


def cannot_switch() -> str | None:
    """Why this host cannot run a command as the account under test; None
    when it can."""
    if not ACCOUNT:
        return "TEST_WORKSPACE_ACCOUNT names no account this process may switch to"
    try:
        switch_to(ACCOUNT)
    except IsolationRefused as refused:
        return refused.message
    return None


needs_an_account = pytest.mark.skipif(cannot_switch() is not None, reason=f"{cannot_switch()}")


def proc_hides_others() -> bool:
    """Whether `/proc` hides another account's processes from this one, as a
    unit with `ProtectProc=invisible` sees it: mounted with `hidepid`, and
    this process outside the group it exempts, root's unless `gid=` names
    another."""
    try:
        mounts = Path("/proc/self/mounts").read_text()
    except OSError:
        return False
    options: dict[str, str] = {}
    for fields in (line.split() for line in mounts.splitlines()):
        if len(fields) > 3 and fields[1] == "/proc":
            pairs = (option.partition("=") for option in fields[3].split(","))
            options = {key: value for key, _, value in pairs}
    exempt = int(options.get("gid", "0"))
    return options.get("hidepid", "0") not in {"0", "off"} and exempt not in {
        os.getgid(),
        *os.getgroups(),
    }


@pytest.fixture
def account_root() -> Iterator[Path]:
    """A root the account passes through, unlike the test's own temporary
    directory, which only this process enters."""
    root = Path(tempfile.mkdtemp(prefix="workspaces-"))
    root.chmod(0o711)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def as_account(records: Path) -> TransportLocalImpl:
    return TransportLocalImpl(
        records, SecretsLocalImpl(None, {}), BrokerNullImpl(), account=ACCOUNT
    )


async def ran(
    transport: TransportLocalImpl, workspace: Workspace, script: str, seconds: float = 30
) -> CommandResult:
    sent = CommandSpec(
        argv=("sh", "-c", script),
        key=new_id(),
        epoch=1,
        deadline=utcnow() + timedelta(seconds=seconds),
    )
    return await transport.run(workspace, sent, seal=RecordSealTwin().seal)


def alive(pid: int) -> bool:
    """Whether `pid` runs, as the kernel answers a signal of none, which no
    `/proc` hides; a zombie, where `/proc` shows one, is dead, whoever reaps
    it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return True
    return not re.search(r"^State:\s+Z", status, re.MULTILINE)


async def still_alive(*pids: int) -> list[int]:
    """The pids still running, given a few seconds to be gone."""
    left = list(pids)
    for _ in range(30):
        if not (left := [pid for pid in pids if alive(pid)]):
            return []
        await asyncio.sleep(0.1)
    return left


@pytest.mark.parametrize("asked", ACCOUNT_REFUSES, ids=lambda s: s.model_dump_json())
async def test_an_account_workspace_refuses_what_it_cannot_hold_and_makes_nothing(
    tmp_path: Path, asked: IsolationSpec
) -> None:
    """Egress, a share of the cpus, and a bound on memory are each refused
    before anything runs: the mode never holds a weaker form of them."""
    root = tmp_path / "workspaces"
    provider = WorkspaceAccountImpl(root, ACCOUNT or "acme-agent")
    with pytest.raises(IsolationRefused):
        await provider.prepare(new_id(), new_id(), asked)
    assert not root.exists(), "nothing is made for a spec that is refused"


async def test_an_account_workspace_on_a_host_that_cannot_switch_is_refused(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspaces"
    provider = WorkspaceAccountImpl(root, "no-such-account-here")
    with pytest.raises(IsolationRefused):
        await provider.prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT, processes=64))
    assert not root.exists()


@needs_an_account
async def test_an_account_workspace_without_the_switchs_capabilities_is_refused(
    monkeypatch: pytest.MonkeyPatch, account_root: Path
) -> None:
    monkeypatch.setattr(accounts, "effective_capabilities", lambda: {5})
    with pytest.raises(IsolationRefused, match="CAP_SETGID, CAP_SETUID, CAP_SETPCAP"):
        await WorkspaceAccountImpl(account_root, ACCOUNT).prepare(
            new_id(), new_id(), spec(IsolationMode.ACCOUNT)
        )
    assert await asyncio.to_thread(os.listdir, account_root) == []


@needs_an_account
async def test_an_account_workspace_on_a_host_that_lets_an_account_link_anothers_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, account_root: Path, tmp_path: Path
) -> None:
    """A hard link the account makes to a file of this process outside the
    workspace would reach it from inside: a host that allows one is refused
    before anything is made."""
    setting = tmp_path / "protected_hardlinks"
    setting.write_text("0\n")
    monkeypatch.setattr(accounts, "HARDLINKS", setting)
    with pytest.raises(IsolationRefused, match="protected_hardlinks"):
        await WorkspaceAccountImpl(account_root, ACCOUNT).prepare(
            new_id(), new_id(), spec(IsolationMode.ACCOUNT)
        )
    assert await asyncio.to_thread(os.listdir, account_root) == []


HIDDEN = "hidden"
"""The host's setting as a unit with `ProcSubset=pid` leaves it: no file."""


@pytest.mark.parametrize(
    ("setting", "declared", "refused"),
    [
        ("0\n", False, "protected_hardlinks is not 1"),
        ("0\n", True, "protected_hardlinks is not 1"),
        (HIDDEN, False, "cannot read fs.protected_hardlinks"),
        (HIDDEN, True, None),
        ("1\n", False, None),
    ],
    ids=["reads-0", "reads-0-declared-on", "hidden", "hidden-declared-on", "reads-1"],
)
async def test_the_hosts_hard_link_setting_is_read_where_it_shows_and_declared_where_it_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    setting: str,
    declared: bool,
    refused: str | None,
) -> None:
    """A host that lets an account link a file it does not own is refused,
    before anything is made, and so is one whose setting this process cannot
    read and the runner's settings do not declare on. The host's own setting
    outranks the declaration; where it is hidden, a declaration lets the
    prepare on, to the hold of the account."""
    path = tmp_path / "protected_hardlinks"
    if setting != HIDDEN:
        path.write_text(setting)
    monkeypatch.setattr(accounts, "HARDLINKS", path)

    def switched(account: str) -> Switch:
        return Switch(account=account, uid=2001, gid=2001, setpriv="setpriv", prlimit="prlimit")

    async def serves_another(*_: object) -> bool:
        return False

    monkeypatch.setattr(accounts, "switch_to", switched)
    monkeypatch.setattr(WorkspaceAccountImpl, "_took", serves_another)
    root = tmp_path / "workspaces"
    infra = InfraConfiguredImpl(
        InfraSettings.model_validate(
            {
                "environment": "local",
                "secrets_file": tmp_path / "secrets.env",
                "workspace_backend": "account",
                "workspaces_root": root,
                "workspace_protected_hardlinks": declared,
            }
        )
    )
    with pytest.raises(IsolationRefused) as caught:
        await infra.get_workspaces().prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT))
    if refused is None:
        assert "one at a time" in caught.value.message, "past the host, to the account's hold"
    else:
        assert refused in caught.value.message and not caught.value.clears
    assert not root.exists()


async def test_only_the_refusal_that_waits_for_the_other_workspace_clears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A prepare refused while the account serves another workspace clears
    once that one is released, so the loop that asked parks and asks again.
    A spec the mode cannot hold, a host that cannot switch, and a host that
    lets an account link another's file never clear: that loop ends."""
    root = tmp_path / "workspaces"
    asked = spec(IsolationMode.ACCOUNT, processes=64)
    never: list[IsolationRefused] = []
    for refused in ACCOUNT_REFUSES:
        with pytest.raises(IsolationRefused) as caught:
            await WorkspaceAccountImpl(root, "acme-agent").prepare(new_id(), new_id(), refused)
        never.append(caught.value)
    with pytest.raises(IsolationRefused) as caught:
        await WorkspaceAccountImpl(root, "no-such-account-here").prepare(new_id(), new_id(), asked)
    never.append(caught.value)

    def switched(account: str) -> Switch:
        return Switch(account=account, uid=2001, gid=2001, setpriv="setpriv", prlimit="prlimit")

    async def serves_another(*_: object) -> bool:
        return False

    monkeypatch.setattr(accounts, "switch_to", switched)
    setting = tmp_path / "protected_hardlinks"
    setting.write_text("0\n")
    monkeypatch.setattr(accounts, "HARDLINKS", setting)
    with pytest.raises(IsolationRefused, match="protected_hardlinks") as caught:
        await WorkspaceAccountImpl(root, "acme-agent").prepare(new_id(), new_id(), asked)
    never.append(caught.value)

    setting.write_text("1\n")
    monkeypatch.setattr(WorkspaceAccountImpl, "_took", serves_another)
    with pytest.raises(IsolationRefused, match="one at a time") as caught:
        await WorkspaceAccountImpl(root, "acme-agent").prepare(new_id(), new_id(), asked)
    assert caught.value.clears
    assert [refused.message for refused in never if refused.clears] == []
    assert not root.exists()


async def test_an_account_holds_each_workspace_from_its_prepare_to_its_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """As a host directory is: a mark beside the workspace's directory, never
    in it, says it is held, so one whose run died before its release is
    found and let go. Its location is the workspace's home."""
    root = tmp_path / "workspaces"

    def switched(account: str) -> Switch:
        return Switch(account=account, uid=2001, gid=2001, setpriv="setpriv", prlimit="prlimit")

    def opened(job: Path, gid: int) -> None:
        (job / accounts.HOME).mkdir(parents=True, exist_ok=True)

    async def serves(*_: object) -> bool:
        return True

    async def done(*_: object) -> None:
        return None

    setting = tmp_path / "protected_hardlinks"
    setting.write_text("1\n")
    monkeypatch.setattr(accounts, "HARDLINKS", setting)
    monkeypatch.setattr(accounts, "switch_to", switched)
    monkeypatch.setattr(accounts, "_opened", opened)
    monkeypatch.setattr(accounts, "end_account", done)
    monkeypatch.setattr(WorkspaceAccountImpl, "_took", serves)
    monkeypatch.setattr(WorkspaceAccountImpl, "_cleared", done)
    provider = WorkspaceAccountImpl(root, "acme-agent")
    org = new_id()
    first, second = [
        await provider.prepare(org, new_id(), spec(IsolationMode.ACCOUNT)) for _ in range(2)
    ]
    assert sorted(await provider.held(), key=lambda held: held.location) == sorted(
        (
            HeldInstance(id=place.id, org_id=org, location=place.location)
            for place in (first, second)
        ),
        key=lambda held: held.location,
    )
    assert await asyncio.to_thread(os.listdir, first.location) == [], "no mark in it"

    await provider.release(first)
    assert [held.id for held in await provider.held()] == [second.id]
    await provider.purge(org, first.id)
    await provider.purge(org, second.id)
    assert await provider.held() == []


@needs_an_account
async def test_a_command_runs_as_the_account_with_no_group_no_capability_and_no_way_to_gain_one(
    monkeypatch: pytest.MonkeyPatch, account_root: Path, tmp_path: Path
) -> None:
    """Its uid and gid, no supplementary group, every capability set empty,
    `no_new_privs`, the processes it asked for at most, and an environment
    of its own, its home and temporary directory in the workspace's."""
    monkeypatch.setenv("ENGINE_OWN", "this process's alone")
    provider = WorkspaceAccountImpl(account_root, ACCOUNT)
    workspace = await provider.prepare(
        new_id(), new_id(), spec(IsolationMode.ACCOUNT, processes=64)
    )
    try:
        script = (
            "id -u; id -g; id -G; sed -n 's/^Max processes *\\([0-9]*\\).*/\\1/p' /proc/self/limits; "
            "echo $HOME; echo $TMPDIR; "
            "grep -E '^(CapInh|CapPrm|CapEff|CapAmb|NoNewPrivs):' /proc/self/status; "
            "env | cut -d= -f1 | sort | tr '\\n' ' '"
        )
        result = await ran(as_account(tmp_path / "records"), workspace, script)
        assert result.exit_code == 0, result.stderr
        uid, gid, groups, processes, home, tmp, *held, names = result.stdout.splitlines()
        account = switch_to(ACCOUNT)
        assert (int(uid), int(gid), groups.split()) == (
            account.uid,
            account.gid,
            [str(account.gid)],
        )
        assert processes == "64"
        assert home == workspace.location and tmp == str(Path(workspace.location).parent / "tmp")
        assert dict(line.split(":\t") for line in held) == {
            "CapInh": "0000000000000000",
            "CapPrm": "0000000000000000",
            "CapEff": "0000000000000000",
            "CapAmb": "0000000000000000",
            "NoNewPrivs": "1",
        }
        assert "ENGINE_OWN" not in names.split() and "TMPDIR" in names.split()
    finally:
        await provider.purge(workspace.org_id, workspace.id)


@needs_an_account
async def test_an_account_release_ends_its_command_and_what_left_its_session_and_a_purge_its_files(
    account_root: Path, tmp_path: Path
) -> None:
    """The account's processes are the workspace's, wherever they run: a
    release ends the command still running and a process it left in a
    session of its own, outside the workspace's directory, and keeps the
    files, which a purge removes."""
    provider = WorkspaceAccountImpl(account_root, ACCOUNT)
    org, workspace_id = new_id(), new_id()
    workspace = await provider.prepare(org, workspace_id, spec(IsolationMode.ACCOUNT))
    transport = as_account(tmp_path / "records")
    script = (
        "(cd / && exec setsid sleep 300 </dev/null >/dev/null 2>&1) & echo $! > left.pid; "
        "echo $$ > command.pid; exec sleep 300"
    )
    command = asyncio.create_task(ran(transport, workspace, script, seconds=120))
    home = Path(workspace.location)
    for _ in range(100):
        if (home / "left.pid").exists() and (home / "command.pid").exists():
            break
        await asyncio.sleep(0.1)
    pids = [int((home / name).read_text()) for name in ("command.pid", "left.pid")]
    assert all(alive(pid) for pid in pids)
    await provider.release(workspace)
    result = await asyncio.wait_for(command, 30)
    assert result.exit_code != 0 and not result.timed_out
    assert await still_alive(*pids) == []
    assert (home / "left.pid").exists(), "a release keeps the files"
    await provider.purge(org, workspace_id)
    assert not home.parent.exists()


@needs_an_account
@pytest.mark.skipif(not proc_hides_others(), reason="/proc here shows every account's processes")
async def test_an_account_release_ends_what_it_left_where_proc_hides_it_from_this_process(
    account_root: Path, tmp_path: Path
) -> None:
    """Where `/proc` hides another account's processes from this one, a
    process the account left running is still ended by the release."""
    provider = WorkspaceAccountImpl(account_root, ACCOUNT)
    org, workspace_id = new_id(), new_id()
    workspace = await provider.prepare(org, workspace_id, spec(IsolationMode.ACCOUNT))
    try:
        script = "(cd / && exec setsid sleep 300 </dev/null >/dev/null 2>&1) & echo $!"
        result = await ran(as_account(tmp_path / "records"), workspace, script)
        assert result.exit_code == 0, result.stderr
        left = int(result.stdout.strip())
        assert alive(left)
        shown = await asyncio.to_thread(os.path.exists, f"/proc/{left}")
        assert not shown, "this process's /proc hides it"
        await provider.release(workspace)
        assert await still_alive(left) == []
    finally:
        await provider.purge(org, workspace_id)


@needs_an_account
async def test_an_account_purge_follows_no_link_the_account_planted_and_clears_what_it_closed(
    account_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.txt").write_text("the engine's")
    before = (outside / "kept.txt").stat()
    provider = WorkspaceAccountImpl(account_root, ACCOUNT)
    workspace = await provider.prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT))
    plant = (
        f"ln -s {outside}/kept.txt file-link; ln -s {outside} dir-link; "
        "mkdir -p closed/deep; touch closed/deep/f; ln -s ../../file-link closed/deep/l; "
        "chmod 500 closed/deep; chmod 0 closed; touch $TMPDIR/scratch"
    )
    result = await ran(as_account(tmp_path / "records"), workspace, plant)
    assert result.exit_code == 0, result.stderr
    await provider.release(workspace)
    await provider.purge(workspace.org_id, workspace.id)
    assert not Path(workspace.location).parent.exists()
    after = (outside / "kept.txt").stat()
    assert (outside / "kept.txt").read_text() == "the engine's"
    assert (after.st_mode, after.st_uid, after.st_mtime) == (
        before.st_mode,
        before.st_uid,
        before.st_mtime,
    )
    assert [path.name for path in outside.iterdir()] == ["kept.txt"]


@needs_an_account
async def test_the_account_serves_one_workspace_at_a_time_and_a_released_one_is_closed_to_it(
    account_root: Path, tmp_path: Path
) -> None:
    provider = WorkspaceAccountImpl(account_root, ACCOUNT)
    transport = as_account(tmp_path / "records")
    first = await provider.prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT))
    second: Workspace | None = None
    try:
        await ran(transport, first, "echo first > notes.txt")
        with pytest.raises(IsolationRefused, match="one at a time"):
            await provider.prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT))
        await provider.release(first)
        second = await provider.prepare(new_id(), new_id(), spec(IsolationMode.ACCOUNT))
        reached = await ran(transport, second, f"cat {first.location}/notes.txt")
        assert reached.exit_code != 0 and "first" not in reached.stdout
        with pytest.raises(IsolationRefused, match="one at a time"):
            await provider.prepare(first.org_id, first.id, spec(IsolationMode.ACCOUNT))
    finally:
        if second is not None:
            await provider.release(second)
            await provider.purge(second.org_id, second.id)
        await provider.purge(first.org_id, first.id)


def hardened() -> str | None:
    """Why this process runs under no unit that hides `/proc/sys`
    (`ProcSubset=pid`) and refuses a setgid bit (`RestrictSUIDSGID=yes`);
    None when it does."""
    if not (accounts.PROC / "self").is_dir() or (accounts.PROC / "sys").exists():
        return "/proc/sys shows here: no unit with ProcSubset=pid"
    probe = Path(tempfile.mkdtemp(prefix="setgid-"))
    try:
        probe.chmod(0o2770)
    except PermissionError:
        return None
    finally:
        probe.rmdir()
    return "a setgid bit is set here: no unit with RestrictSUIDSGID=yes"


def processes_of(uid: int) -> list[int]:
    """The live processes `/proc` shows whose real, effective, or saved uid
    is `uid`."""
    found: list[int] = []
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            text = status.read_text()
        except OSError:
            continue
        uids = re.search(r"^Uid:\s+(\d+)\s+(\d+)\s+(\d+)", text, re.MULTILINE)
        state = re.search(r"^State:\s+(\S)", text, re.MULTILINE)
        if uids and str(uid) in uids.groups() and not (state and state.group(1) in "ZX"):
            found.append(int(status.parent.name))
    return found


@needs_an_account
@pytest.mark.skipif(hardened() is not None, reason=f"{hardened()}")
async def test_under_a_hardened_unit_a_workspace_prepares_runs_as_the_account_releases_and_purges(
    account_root: Path, tmp_path: Path
) -> None:
    """Under a unit that hides `/proc/sys` and refuses a setgid bit, with the
    host's setting declared on: the home and the temporary directory carry
    no setgid bit, and the account writes both; a file this process writes
    there, the account reads, and one the account writes, this process
    reads. A release ends every process of the account and closes the
    workspace; a purge removes it and follows no link the account
    planted."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.txt").write_text("the engine's")
    account = switch_to(ACCOUNT)
    provider = WorkspaceAccountImpl(account_root, ACCOUNT, protected_hardlinks=True)
    transport = as_account(tmp_path / "records")
    workspace = await provider.prepare(
        new_id(), new_id(), spec(IsolationMode.ACCOUNT, processes=64)
    )
    home = Path(workspace.location)
    try:
        for shared in (home, accounts.temporary(home)):
            made = shared.stat()
            assert (stat.S_IMODE(made.st_mode), made.st_gid) == (0o770, account.gid)
        await transport.write_file(workspace, "src/in.txt", b"the engine's file", epoch=1)
        script = (
            "set -e; cat src/in.txt; echo; echo the account > src/out.txt; "
            'touch "$HOME/home-file" "$TMPDIR/tmp-file"; '
            f"ln -s {outside}/kept.txt file-link; ln -s {outside} dir-link; "
            "(cd / && exec setsid sleep 300 </dev/null >/dev/null 2>&1) & echo $!"
        )
        result = await ran(transport, workspace, script)
        assert result.exit_code == 0, result.stderr
        read, left = result.stdout.splitlines()
        assert read == "the engine's file"
        assert await transport.read_file(workspace, "src/out.txt", 100) == b"the account\n"
        for written in (home / "home-file", accounts.temporary(home) / "tmp-file"):
            assert written.stat().st_uid == account.uid
        assert alive(int(left))
        await provider.release(workspace)
        assert await still_alive(int(left)) == []
        assert processes_of(account.uid) == []
        assert stat.S_IMODE(home.parent.stat().st_mode) == 0o700, "closed to the account"
    finally:
        await provider.purge(workspace.org_id, workspace.id)
    assert not home.parent.exists()
    assert (outside / "kept.txt").read_text() == "the engine's"
    assert [path.name for path in outside.iterdir()] == ["kept.txt"]
