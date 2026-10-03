import hashlib
from datetime import timedelta
from uuid import UUID

from acme.infra.docker import docker
from acme.infra.exceptions import BackendFailed
from acme.infra.workspaces import (
    EgressMode,
    HeldInstance,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
    Workspace,
    WorkspaceProviderInterface,
    refusal,
)
from acme.infra.workspaces.network import NO_HOST_NETWORK, HostNetwork

MOUNT = "/workspace"
"""Where a workspace's files sit inside its container."""

CA_MOUNT = "/etc/ssl/host-ca.pem"
"""Where the host's CA file sits inside a container with open egress, read
only."""

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


def container_name(workspace_id: UUID) -> str:
    """The container's name, and its volume's: one per workspace."""
    return f"acme-ws-{workspace_id.hex}"


def spec_print(spec: IsolationSpec, *mounts: str) -> str:
    """The fingerprint of a spec and the host's files mounted for it, as a
    container started to them is labelled: a running container is reused
    only under the spec and the mounts it was started to."""
    return hashlib.sha256("\n".join((spec.model_dump_json(), *mounts)).encode()).hexdigest()


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

    The container drops every capability, takes no new privileges, and
    keeps nothing of the engine's environment: its variables are the
    image's. Under open egress it holds the host's CA file read-only at
    `CA_MOUNT`, and under any other egress nothing of the host's."""

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

    async def prepare(self, org_id: UUID, workspace_id: UUID, spec: IsolationSpec) -> Workspace:
        why = refusal(
            spec,
            mode=IsolationMode.CONTAINER,
            egress={EgressMode.NONE, EgressMode.OPEN},
            limits=LIMIT_FLAGS.keys(),
        )
        if why is not None:
            raise IsolationRefused(why)
        reachable = await docker("version", "--format", "{{.Server.Version}}", bound=self._timeout)
        if not reachable.ok:
            raise IsolationRefused(f"a container workspace needs Docker: {reachable.reason()}")
        name = container_name(workspace_id)
        workspace = Workspace(id=workspace_id, org_id=org_id, spec=spec, location=name)
        running = await docker("inspect", "--format", STARTED_TO, name, bound=self._timeout)
        mounts = self._mounts(spec)
        printed = spec_print(spec, *mounts)
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
        present = await docker(
            "image", "inspect", "--format", "{{.Id}}", self._image, bound=self._timeout
        )
        if not present.ok:
            # Pulled on its own limit, so a prepare's run never carries the
            # pull: a run killed mid-pull leaves no image behind.
            pulled = await docker("pull", self._image, bound=self._pull_timeout)
            if not pulled.ok:
                raise BackendFailed("docker", "pull", pulled.reason())
        labels = (
            "--label",
            f"{WORKSPACE_LABEL}={workspace_id}",
            "--label",
            f"{ORG_LABEL}={org_id}",
            "--label",
            f"{DEPLOYMENT_LABEL}={self._deployment}",
        )
        made = await docker("volume", "create", *labels, name, bound=self._timeout)
        if not made.ok:
            raise BackendFailed("docker", "volume create", made.reason())
        started = await docker(
            "run",
            "--detach",
            "--init",
            "--name",
            name,
            *labels,
            "--label",
            f"{SPEC_LABEL}={printed}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            *_network(spec),
            *_limits(spec),
            *(flag for mount in mounts for flag in ("--mount", mount)),
            "--volume",
            f"{name}:{MOUNT}",
            "--workdir",
            MOUNT,
            self._image,
            "sleep",
            "infinity",
            bound=self._timeout,
        )
        if not started.ok:
            raise BackendFailed("docker", "run", started.reason())
        return workspace

    async def release(self, workspace: Workspace) -> None:
        await docker("rm", "-f", workspace.location, bound=self._timeout)

    async def purge(self, org_id: UUID, workspace_id: UUID) -> None:
        name = container_name(workspace_id)
        for removal in (("rm", "-f", name), ("volume", "rm", "-f", name)):
            removed = await docker(*removal, bound=self._timeout)
            if not removed.ok:
                raise BackendFailed("docker", " ".join(removal[:-2]), removed.reason())

    async def held(self) -> list[HeldInstance]:
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

    def _mounts(self, spec: IsolationSpec) -> tuple[str, ...]:
        """The host's files a container to `spec` holds: its CA file, read
        only, under open egress alone. A bind `--mount` refuses a source
        that is not there, where a `--volume` would make one."""
        ca_file = self._network.ca_file
        if spec.egress.mode is not EgressMode.OPEN or ca_file is None:
            return ()
        return (f"type=bind,source={ca_file},target={CA_MOUNT},readonly",)

    def describe(self) -> str:
        return f"workspaces=container({self._image})"

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


def _network(spec: IsolationSpec) -> tuple[str, ...]:
    return ("--network", "none") if spec.egress.mode is EgressMode.NONE else ()


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
