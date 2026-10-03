"""Isolation is chosen up front and never weakened. A provider meets a spec
whole or refuses it, before it creates anything, and never hands back a
weaker place: not the host directory for a container, and not a container
with open egress for one that asked for none. A container holds the host's
CA file, read-only, under open egress alone. A host directory's release ends
what its commands left running there."""

import asyncio
import contextlib
import io
import os
import re
import signal
import subprocess
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from acme.infra.base import new_id
from acme.infra.docker import DockerReply
from acme.infra.docker import docker as docker_cli
from acme.infra.exceptions import BackendFailed
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
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
from acme.infra.workspaces.container import (
    CA_PATH,
    DOCKER_PROXIES,
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
    Docker does. It keeps every command it is given, and what each was fed
    on its input."""

    def __init__(self) -> None:
        self.labels: dict[str, str] | None = None  # the running container's, when one runs
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
        if args[0] == "create":
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
    assert [call[0] for call in docker.calls] == [*STARTED_AGAIN[:-1], "cp", "start"]
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
    for mode in (IsolationMode.VM, IsolationMode.CONTAINER, IsolationMode.HOST):
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
