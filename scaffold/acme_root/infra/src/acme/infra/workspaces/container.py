import hashlib
import io
import json
import re
import tarfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import IO
from uuid import UUID

from acme.infra.docker import docker, docker_stream
from acme.infra.exceptions import BackendFailed
from acme.infra.workspaces import (
    EgressMode,
    HeldInstance,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    SnapshotRefused,
    Workspace,
    WorkspaceLost,
    WorkspaceProviderInterface,
    refusal,
)
from acme.infra.workspaces.network import NO_HOST_NETWORK, HostNetwork

MOUNT = "/workspace"
"""Where a workspace's files sit inside its container."""

CA_PATH = "/etc/ssl/host-ca.pem"
"""Where a container with open egress holds a copy of the host's CA file,
which no command there can write."""

DOCKER_PROXIES = tuple(
    name
    for upper in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
    for name in (upper, upper.lower())
)
"""The variables the `docker` command line fills, in every container it
starts, from the proxies its own config file names, credentials included,
whatever the container's network. A container is started with each named
and no value, which the command line's own environment never holds
(`DOCKER_VARIABLES`), so each is left unset: the only proxy a command sees
is the one its transport hands it."""

DEFAULT_IMAGE = "python:3.14"
"""The image a container workspace runs unless a setting names another. An
image holds what runs in the workspace: Python for its tools, and `git`,
which checks out and pushes a session's repository inside it."""

DEFAULT_PULL_TIMEOUT = timedelta(seconds=900)
"""How long `docker pull` of the image may run. It is longer than any other
command's limit: an image is hundreds of megabytes, and Docker discards the
layers of a pull that is killed, so a limit too short for a slow link never
lets the image arrive."""

LIMIT_FLAGS = {"cpus": "--cpus", "memory_mb": "--memory", "processes": "--pids-limit"}


WORKSPACE_LABEL = "acme.workspace"
"""The label that names the workspace a container, and its volume, hold."""

ORG_LABEL = "acme.org"
"""The label that names the tenant of that workspace."""

OPEN_NETWORK = "acme-ws-open"
"""The bridge every workspace with open egress joins, made with traffic
between its containers off: a workspace reaches out, never into another
tenant's workspace."""

ICC = "com.docker.network.bridge.enable_icc"
"""The bridge option that lets its containers reach each other."""

SPEC_LABEL = "acme.spec"
"""The label that names the spec a container was started to."""

DEPLOYMENT_LABEL = "acme.deployment"
"""The label that names the deployment that started a container, and made
its volume: a provider holds only its own deployment's, so two deployments
on one Docker never let go of each other's."""

HELD_AS = '{{.Names}} {{.Label "' + WORKSPACE_LABEL + '"}} {{.Label "' + ORG_LABEL + '"}}'
"""What a listing answers of each running container: its name, and the
workspace and the tenant its labels name."""

STARTED_TO = (
    '{{.State.Running}} {{index .Config.Labels "'
    + SPEC_LABEL
    + '"}} {{index .Config.Labels "'
    + DEPLOYMENT_LABEL
    + '"}}'
)
"""What an inspect answers of a container: whether it runs, the spec it was
started to, and the deployment that started it."""

RUNS_ON = "{{.State.Running}} {{.Image}}"
"""What an inspect answers of a container: whether it runs, and the id of the
image it runs on."""

FORMAT = "acme.container-snapshot/1"
"""What a container's snapshot says it is, in its manifest."""

DOCKERS_OWN = frozenset(
    {"/.dockerenv", "/etc/hostname", "/etc/hosts", "/etc/resolv.conf"}
    | {"/sbin/docker-init", "/usr/sbin/docker-init"}
)
"""What Docker writes into each container it starts: never a command's, so
never kept, and written again by the container a snapshot restores."""

GIVEN = frozenset({CA_PATH})
"""What this provider copies into a container before it starts: never a
command's, so never kept, and given again, as the host holds it then, to
the container a snapshot restores."""

MOUNTED = (MOUNT, "/proc", "/sys", "/dev")
"""Where a container's writable layer holds nothing of its own: the
workspace's volume, kept apart, and what the kernel mounts."""

IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")

REPO_DIGESTS = "{{json .RepoDigests}}"
"""What an inspect answers of an image: the references a registry serves it
under, each pinned by its digest."""

REPO_DIGEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64}$")
"""A reference another daemon pulls an image by: a repository and the digest
that pins it, never a tag that may have moved."""

SETUP_DROPS = "NET_RAW"
"""What a setup's container drops of the runtime's default capabilities:
raw sockets, which no package manager needs, on a network other tenants'
containers may share."""

REMOVE = 'while IFS= read -r path; do rm -rf -- "$path" || exit 1; done'
"""Removes each path its input names, one a line."""


def container_name(workspace_id: UUID) -> str:
    """The container's name, and its volume's: one per workspace."""
    return f"acme-ws-{workspace_id.hex}"


def spec_print(spec: IsolationSpec, *given: str, building: bool = False) -> str:
    """The fingerprint of a spec, and of what else a container started to
    it was given (`_given`), as that container is labelled: a running
    container is reused only under what it was started to, and a setup's,
    which holds capabilities, never as any other."""
    started_to = spec.model_dump_json() + ("+building" if building else "")
    return hashlib.sha256("\n".join((started_to, *given)).encode()).hexdigest()


def ca_archive(ca: bytes) -> bytes:
    """The archive `docker cp` unpacks at the container's root: the CA file
    at `CA_PATH`, readable by all and writable by none, so a command with no
    capabilities cannot change it."""
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w") as archive:
        entry = tarfile.TarInfo(CA_PATH.lstrip("/"))
        entry.size, entry.mode = len(ca), 0o444
        archive.addfile(entry, io.BytesIO(ca))
    return packed.getvalue()


class WorkspaceContainerImpl(WorkspaceProviderInterface):
    """A container per workspace on the local Docker, with its files in a
    volume of its own that outlives the container. It meets the container
    mode with no egress or open egress, and every resource limit. A running
    container is reused only under the spec it was started to; under any
    other, a tightened one included, it is replaced and its files kept. An
    allowlist needs an egress proxy this provider does not run, so it is
    refused; so is every spec when Docker cannot be reached. There is no
    weaker place to fall back to.

    Every container and volume it makes carries its deployment's label, and
    it holds only those that carry it: a running container without it is
    replaced at its next prepare, its files kept.

    A workspace's container drops every capability, takes no new
    privileges, and keeps nothing of the engine's environment: its
    variables are the image's, with no proxy (`DOCKER_PROXIES`). With no
    egress it has no network; with open egress it joins `OPEN_NETWORK`,
    where no container reaches another. What the host itself answers on the
    bridge, its metadata service included, is the host's to close (ADR
    1017). Its hostname is its name, the same for every container the
    workspace runs in. Under open egress it holds a copy of the host's CA
    file at `CA_PATH`, copied in before it starts, and under any other
    egress nothing of the host's. The copy is of the content the host read
    when it started (`HostNetwork`): a prepare never reads the host's file,
    nor asks Docker to reach the host's path.

    A snapshot holds the container's whole filesystem: its writable layer,
    as `docker diff` names what changed in it, and its volume, with the
    paths removed from the image. It never holds the CA file (`GIVEN`): a
    restored container is given the host's own again. It names the image
    beneath by its id and by the digest a registry serves it under, when it
    has one. It is taken with the container paused, so nothing writes while
    it is. A restore starts a container on that image, pulled by its digest
    on a host that lacks it, and copies both back, owners and modes kept
    (ADR 1027).

    A base is the image it names, or, with setup, a snapshot of a container
    its setup ran in. Each container on it starts on the image that
    snapshot names, with the setup's layer copied in; its files are copied
    into the volume only when the volume is new, so a workspace found again
    keeps its own (ADR 1028). A setup is given open egress or none, as a
    workspace is. Its container holds the runtime's default capabilities
    less raw sockets, so a package manager can change owners and drop to
    its own user; it takes no new privileges and is never privileged."""

    def __init__(
        self,
        image: str,
        timeout: timedelta,
        deployment: str,
        pull_timeout: timedelta = DEFAULT_PULL_TIMEOUT,
        network: HostNetwork = NO_HOST_NETWORK,
    ) -> None:
        self._image = image
        self._timeout = timeout
        self._deployment = deployment
        self._pull_timeout = pull_timeout
        self._network = network

    async def prepare(
        self,
        org_id: UUID,
        workspace_id: UUID,
        spec: IsolationSpec,
        snapshot: bytes | None = None,
        base: bytes | None = None,
        *,
        building: bool = False,
    ) -> Workspace:
        why = refusal(
            spec,
            mode=IsolationMode.CONTAINER,
            egress={EgressMode.NONE, EgressMode.OPEN},
            limits=LIMIT_FLAGS.keys(),
        )
        built = snapshot is None and spec.base is not None and bool(spec.base.setup)
        if why is None and built and base is None:
            why = "a workspace on a base with setup starts from the base's snapshot alone"
        if why is not None:
            raise IsolationRefused(why)
        reachable = await docker("version", "--format", "{{.Server.Version}}", bound=self._timeout)
        if not reachable.ok:
            raise IsolationRefused(f"a container workspace needs Docker: {reachable.reason()}")
        name = container_name(workspace_id)
        workspace = Workspace(id=workspace_id, org_id=org_id, spec=spec, location=name)
        if snapshot is not None:
            return await self._restore(workspace, snapshot)
        running = await docker("inspect", "--format", STARTED_TO, name, bound=self._timeout)
        printed = self._print(spec, building=building)
        started_to = [b"true", printed.encode(), self._deployment.encode()]
        if running.ok and running.stdout.split() == started_to:
            return workspace
        if running.ok:
            # A container left stopped, or started to another spec, such as
            # one tightened since, or without this deployment's label: its
            # instance goes, its files stay, and the container that
            # replaces it holds this spec and carries the label.
            removed = await docker("rm", "-f", name, bound=self._timeout)
            if not removed.ok:
                raise BackendFailed("docker", "rm", removed.reason())
        if built and base is not None:
            await self._start_on_base(workspace, _opened(base))
        else:
            image = self._named_image(spec)
            await self._present(image)
            await self._start(workspace, image, building=building)
        return workspace

    async def snapshot(self, workspace: Workspace) -> bytes:
        name = workspace.location
        shown = await docker("inspect", "--format", RUNS_ON, name, bound=self._timeout)
        running = shown.stdout.split()
        if not shown.ok or len(running) != 2 or running[0] != b"true":
            raise SnapshotRefused(f"workspace {workspace.id} holds no instance to snapshot")
        image = running[1].decode()
        pull = await self._pullable(image)
        paused = await docker("pause", name, bound=self._timeout)
        if not paused.ok:
            raise BackendFailed("docker", "pause", paused.reason())
        try:
            changed = await docker("diff", name, bound=self._timeout)
            if not changed.ok:
                raise BackendFailed("docker", "diff", changed.reason())
            kept, deleted = _changes(changed.stdout.decode())
            layer = b""
            if kept:
                exported, read = await docker_stream(
                    "export", name, bound=self._timeout, read=lambda out: _layer(out, kept)
                )
                if read is None:
                    raise BackendFailed("docker", "export", exported.reason())
                layer = read
            files = await docker("cp", f"{name}:{MOUNT}", "-", bound=self._timeout)
            if not files.ok:
                raise BackendFailed("docker", "cp", files.reason())
        finally:
            unpaused = await docker("unpause", name, bound=self._timeout)
        if not unpaused.ok:
            raise BackendFailed("docker", "unpause", unpaused.reason())
        return _archive(
            Kept(image=image, pull=pull, deleted=deleted, layer=layer, files=files.stdout)
        )

    async def release(self, workspace: Workspace) -> None:
        await docker("rm", "-f", workspace.location, bound=self._timeout)

    async def held_instances(self) -> list[HeldInstance]:
        """The running containers this provider started: labelled with a
        workspace, a tenant, and this deployment, and named for that
        workspace. A stopped one holds nothing that runs, and its next
        prepare replaces it."""
        listed = await docker(
            "ps",
            "--filter",
            f"label={WORKSPACE_LABEL}",
            "--filter",
            f"label={DEPLOYMENT_LABEL}={self._deployment}",
            "--format",
            HELD_AS,
            bound=self._timeout,
        )
        if not listed.ok:
            raise BackendFailed("docker", "ps", listed.reason())
        found = (_held(line) for line in listed.stdout.decode(errors="replace").splitlines())
        return [instance for instance in found if instance is not None]

    def _ca(self, spec: IsolationSpec) -> bytes | None:
        """The CA file a container to `spec` holds: the host's, under open
        egress alone."""
        return self._network.ca if spec.egress.mode is EgressMode.OPEN else None

    def _print(self, spec: IsolationSpec, *, building: bool = False) -> str:
        """The print a container started to `spec` here is labelled with."""
        return spec_print(spec, *_given(self._ca(spec)), building=building)

    async def _present(self, image: str) -> None:
        """`image` on this host, pulled on its own limit when it is absent, so
        a prepare's run never carries the pull: a run killed mid-pull leaves
        no image behind."""
        present = await docker(
            "image", "inspect", "--format", "{{.Id}}", image, bound=self._timeout
        )
        if not present.ok:
            pulled = await docker("pull", image, bound=self._pull_timeout)
            if not pulled.ok:
                raise BackendFailed("docker", "pull", pulled.reason())

    async def _pullable(self, image: str) -> str | None:
        """The reference another daemon pulls `image` by: the first of the
        digests a registry serves it under, or None for an image no registry
        serves, such as one built on this host."""
        shown = await docker(
            "image", "inspect", "--format", REPO_DIGESTS, image, bound=self._timeout
        )
        if not shown.ok:
            raise BackendFailed("docker", "image inspect", shown.reason())
        served = json.loads(shown.stdout or b"null") or []
        return min((ref for ref in served if REPO_DIGEST.match(ref)), default=None)

    async def purge(self, org_id: UUID, workspace_id: UUID) -> None:
        await self._remove(container_name(workspace_id))

    async def _remove(self, name: str) -> None:
        """The container and its volume gone; one already gone is no error."""
        for removal in (("rm", "-f", name), ("volume", "rm", "-f", name)):
            removed = await docker(*removal, bound=self._timeout)
            if not removed.ok:
                raise BackendFailed("docker", " ".join(removal[:-2]), removed.reason())

    async def _start(self, workspace: Workspace, image: str, *, building: bool = False) -> None:
        """The workspace's volume, made when it is missing, and a container
        on `image` that mounts it, started to the workspace's spec: with no
        capability, or, `building`, with a setup's. It is created, given
        the CA file its spec holds, then started: a container never runs
        without what its spec holds. One left created and not started, by a
        failure here, is replaced at the next prepare."""
        name, spec = workspace.location, workspace.spec
        labels = (
            "--label",
            f"{WORKSPACE_LABEL}={workspace.id}",
            "--label",
            f"{ORG_LABEL}={workspace.org_id}",
            "--label",
            f"{DEPLOYMENT_LABEL}={self._deployment}",
        )
        made = await docker("volume", "create", *labels, name, bound=self._timeout)
        if not made.ok:
            raise BackendFailed("docker", "volume create", made.reason())
        if spec.egress.mode is EgressMode.OPEN:
            await self._open_network()
        ca = self._ca(spec)
        created = await docker(
            "create",
            "--init",
            "--name",
            name,
            "--hostname",
            name,
            *labels,
            "--label",
            f"{SPEC_LABEL}={self._print(spec, building=building)}",
            "--cap-drop",
            SETUP_DROPS if building else "ALL",
            "--security-opt",
            "no-new-privileges",
            *_network(spec),
            *_limits(spec),
            *(flag for variable in DOCKER_PROXIES for flag in ("--env", variable)),
            "--volume",
            f"{name}:{MOUNT}",
            "--workdir",
            MOUNT,
            image,
            "sleep",
            "infinity",
            bound=self._timeout,
        )
        if not created.ok:
            raise BackendFailed("docker", "create", created.reason())
        if ca is not None:
            copied = await docker("cp", "-", f"{name}:/", stdin=ca_archive(ca), bound=self._timeout)
            if not copied.ok:
                raise BackendFailed("docker", "cp", copied.reason())
        started = await docker("start", name, bound=self._timeout)
        if not started.ok:
            raise BackendFailed("docker", "start", started.reason())

    async def _restore(self, workspace: Workspace, snapshot: bytes) -> Workspace:
        """The workspace replaced whole by what `snapshot` holds: a container
        on the image it names, its writable layer and its volume copied back,
        and the paths removed from the image removed again. The image is
        named by its id, never by a tag that may have moved. A restore that
        fails part way removes what it made, so no half-restored workspace is
        ever found again."""
        kept = _opened(snapshot)
        await self._bring_image(kept)
        name = workspace.location
        await self._remove(name)
        try:
            await self._start(workspace, kept.image)
            await self._unpack(name, kept, files=True)
        except BaseException:
            await self._remove(name)
            raise
        return workspace

    async def _start_on_base(self, workspace: Workspace, kept: Kept) -> None:
        """A container started from a base's snapshot: on the image it names,
        with the setup's layer copied in and the paths the setup removed
        removed again, and the setup's files copied into the volume only when
        the volume is new. One that fails part way removes the container,
        and the volume only when it was new: the workspace's own files are
        never lost to a base."""
        await self._bring_image(kept)
        name = workspace.location
        listed = await docker(
            "volume", "ls", "--quiet", "--filter", f"name={name}", bound=self._timeout
        )
        if not listed.ok:
            raise BackendFailed("docker", "volume ls", listed.reason())
        new = name.encode() not in listed.stdout.split()
        try:
            await self._start(workspace, kept.image)
            await self._unpack(name, kept, files=new)
        except BaseException:
            if new:
                await self._remove(name)
            else:
                await docker("rm", "-f", name, bound=self._timeout)
            raise

    async def _unpack(self, name: str, kept: Kept, *, files: bool) -> None:
        """What `kept` holds copied into the container under `name`: its
        writable layer, owners and modes kept, then its volume's files when
        `files`, and the paths removed from the image removed again."""
        for part in (kept.layer, kept.files if files else b""):
            if part:
                copied = await docker(
                    "cp", "--archive", "-", f"{name}:/", stdin=part, bound=self._timeout
                )
                if not copied.ok:
                    raise BackendFailed("docker", "cp", copied.reason())
        if kept.deleted:
            paths = "".join(f"{path}\n" for path in kept.deleted).encode()
            removed = await docker(
                "exec", "--interactive", name, "sh", "-c", REMOVE, stdin=paths, bound=self._timeout
            )
            if not removed.ok:
                raise BackendFailed("docker", "exec", removed.reason())

    def _named_image(self, spec: IsolationSpec) -> str:
        """The image a spec names: its base's, or this provider's own."""
        return self._image if spec.base is None else spec.base.image

    async def _bring_image(self, kept: Kept) -> None:
        """The image a snapshot was taken on, on this host: found by its id,
        or pulled by the digest the snapshot names and held to that id. One
        that cannot be had loses the workspace, with the reason, before
        anything of it is removed."""
        if (await docker("image", "inspect", kept.image, bound=self._timeout)).ok:
            return
        taken_on = f"the image {kept.image} the snapshot was taken on"
        if kept.pull is None:
            raise WorkspaceLost(f"{taken_on} is not on this host, and no registry serves it")
        pulled = await docker("pull", kept.pull, bound=self._pull_timeout)
        if not pulled.ok:
            raise WorkspaceLost(f"{taken_on} is not on this host: {pulled.reason()}")
        if not (await docker("image", "inspect", kept.image, bound=self._timeout)).ok:
            raise WorkspaceLost(f"{kept.pull} pulled an image other than {taken_on}")

    async def held(self, snapshot: bytes) -> AsyncIterator[bytes]:
        yield snapshot  # its archive holds its bytes

    async def keep(self, snapshot: bytes, org_id: UUID, workspace_id: UUID) -> bytes:
        return snapshot

    async def discard(self, snapshot: bytes) -> None:
        return None

    async def erase_snapshots(self, org_id: UUID, workspace_id: UUID) -> None:
        return None

    def describe(self) -> str:
        return f"workspaces=container({self._image})"

    async def _open_network(self) -> None:
        """`OPEN_NETWORK`, made once, with traffic between its containers
        off. One that stands with that traffic on, however it was made, is
        refused: a workspace that joined it could reach every other."""
        icc = await self._icc()
        if icc is None:
            made = await docker(
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                f"{ICC}=false",
                OPEN_NETWORK,
                bound=self._timeout,
            )
            # Another prepare may have made it first; it is read again.
            icc = "false" if made.ok else await self._icc()
            if icc is None:
                raise BackendFailed("docker", "network create", made.reason())
        if icc != "false":
            raise IsolationRefused(
                f"the network {OPEN_NETWORK} lets its containers reach each other"
            )

    async def _icc(self) -> str | None:
        """What `OPEN_NETWORK` says of traffic between its containers, or
        None when it does not stand."""
        shown = await docker(
            "network",
            "inspect",
            "--format",
            '{{index .Options "' + ICC + '"}}',
            OPEN_NETWORK,
            bound=self._timeout,
        )
        return shown.stdout.decode().strip() if shown.ok else None

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _held(line: str) -> HeldInstance | None:
    """A container's line of the listing, when it is one this provider
    started; None for any other, such as one labelled by hand under
    another name."""
    words = line.split()
    if len(words) != 3:
        return None
    name, workspace, org = words
    try:
        workspace_id, org_id = UUID(workspace), UUID(org)
    except ValueError:
        return None
    if name != container_name(workspace_id):
        return None
    return HeldInstance(id=workspace_id, org_id=org_id, location=name)


def _given(ca: bytes | None) -> tuple[str, ...]:
    """What a container holds beyond its spec, as its print names it: the
    proxies left unset, and the CA file's digest when it holds one. A
    container started before either is replaced, its files kept."""
    unset = "unset=" + ",".join(DOCKER_PROXIES)
    return (unset,) if ca is None else (unset, "ca=" + hashlib.sha256(ca).hexdigest())


def _network(spec: IsolationSpec) -> tuple[str, ...]:
    """No network with no egress, and the shared bridge where no container
    reaches another with open egress: never Docker's default bridge, where
    every container reaches every other."""
    return ("--network", "none" if spec.egress.mode is EgressMode.NONE else OPEN_NETWORK)


def _limits(spec: IsolationSpec) -> tuple[str, ...]:
    flags: list[str] = []
    limits = spec.limits
    if limits.cpus is not None:
        flags += [LIMIT_FLAGS["cpus"], str(limits.cpus)]
    if limits.memory_mb is not None:
        flags += [LIMIT_FLAGS["memory_mb"], f"{limits.memory_mb}m"]
    if limits.processes is not None:
        flags += [LIMIT_FLAGS["processes"], str(limits.processes)]
    return tuple(flags)


@dataclass(frozen=True)
class Kept:
    """What a container's snapshot holds: the image beneath it, by id, and the
    digest another daemon pulls it by, when a registry serves it; the paths
    its commands removed from the image; and, as two archives, what changed
    in its writable layer and what its volume holds."""

    image: str
    pull: str | None
    deleted: tuple[str, ...]
    layer: bytes
    files: bytes


def _within(path: str, place: str) -> bool:
    return path == place or path.startswith(place.rstrip("/") + "/")


def _changes(diff: str) -> tuple[frozenset[str], tuple[str, ...]]:
    """What `docker diff` names: the paths added or changed in the writable
    layer, and those removed from the image, past the volume, what the
    kernel mounts, what Docker writes into every container, and what this
    provider gives one before it starts."""
    kept: set[str] = set()
    deleted: list[str] = []
    for line in diff.splitlines():
        change, _, path = line.partition(" ")
        if path in DOCKERS_OWN or path in GIVEN or any(_within(path, place) for place in MOUNTED):
            continue
        if change == "D":
            deleted.append(path)
        elif change in ("A", "C"):
            kept.add(path)
    return frozenset(kept), tuple(deleted)


def _layer(export: IO[bytes], kept: frozenset[str]) -> bytes:
    """The members of a container's export that `kept` names, in its order,
    an archive of their own: what changed in its writable layer, read from
    the stream, so the image beneath is never held."""
    out = io.BytesIO()
    with (
        tarfile.open(fileobj=export, mode="r|") as source,
        tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as layer,
    ):
        for member in source:
            if "/" + member.name.removeprefix("./").rstrip("/") in kept:
                layer.addfile(member, source.extractfile(member) if member.isreg() else None)
    return out.getvalue()


def _archive(kept: Kept) -> bytes:
    """A snapshot's bytes: its manifest, then its two archives."""
    manifest = {
        "format": FORMAT,
        "image": kept.image,
        "pull": kept.pull,
        "deleted": list(kept.deleted),
    }
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in (
            ("manifest.json", json.dumps(manifest).encode()),
            ("layer.tar", kept.layer),
            ("workspace.tar", kept.files),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(data))
    return out.getvalue()


def _opened(snapshot: bytes) -> Kept:
    """What `_archive` wrote. Anything else, such as another provider's
    snapshot, is no workspace this provider can bring in."""
    try:
        parts: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:") as archive:
            for member in archive.getmembers():
                handle = archive.extractfile(member) if member.isreg() else None
                if handle is not None:
                    parts[member.name] = handle.read()
        manifest = json.loads(parts["manifest.json"])
        image, deleted = manifest["image"], tuple(manifest["deleted"])
        format_, pull = manifest["format"], manifest.get("pull")
    except (tarfile.TarError, KeyError, TypeError, ValueError) as error:
        raise WorkspaceLost(f"the snapshot is no container's: {error}") from error
    if format_ != FORMAT:
        raise WorkspaceLost(f"the snapshot is {format_!r}, not a container's")
    if not isinstance(image, str) or not IMAGE_ID.match(image):
        raise WorkspaceLost("the snapshot names no image by its id")
    if pull is not None and (not isinstance(pull, str) or not REPO_DIGEST.match(pull)):
        raise WorkspaceLost("the snapshot names its image's digest by no reference to pull")
    if not all(
        isinstance(path, str) and path.startswith("/") and "\n" not in path for path in deleted
    ):
        raise WorkspaceLost("the snapshot names a removed path that is not one")
    return Kept(
        image=image,
        pull=pull,
        deleted=deleted,
        layer=parts.get("layer.tar", b""),
        files=parts.get("workspace.tar", b""),
    )
