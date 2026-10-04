"""What a host checks at startup, before it enrolls or claims: that it
reaches what it needs (its trust store, its proxy, the platform, a sane
clock), so a misconfigured host fails at startup and never mid-session;
which isolation modes it can provide; and whether it reaches a cloud's
metadata service, which keeps open egress off it. It advertises its
operating system and shell, its capabilities, and the modes whose probe
passed, and nothing else: there is no setting that names a mode, so a
mode no probe showed is never advertised."""

import os
import platform
import pwd
import shutil
import socket
import ssl
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import truststore

from acme.client.client import ApiClient
from acme.client.types import AdvertisementBody, IsolationMode

PROBE_TIMEOUT_SECONDS = 10.0
"""The longest one probe's command may run."""

PROXY_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


@dataclass(frozen=True)
class Probe:
    """One check and what it found."""

    name: str
    passed: bool
    detail: str


PASSES_WITH_TIME = frozenset({"platform", "clock"})
"""The startup probes whose failure passes without a person: the platform
comes back, and the machine's clock comes into step."""


class Misconfigured(RuntimeError):
    """A startup probe failed: the host does not start, and says which."""

    def __init__(self, failed: list[Probe]) -> None:
        super().__init__("; ".join(f"{probe.name}: {probe.detail}" for probe in failed))
        self.failed = failed

    @property
    def passes_with_time(self) -> bool:
        """Whether every failed probe is one that passes with time, so a
        later start may succeed where this one did not."""
        return all(probe.name in PASSES_WITH_TIME for probe in self.failed)


# The startup probes.


def trust_store() -> Probe:
    """The system trust store loads, and a CA file the environment names
    exists and loads with it."""
    try:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        named = os.environ.get("SSL_CERT_FILE")
        if named:
            context.load_verify_locations(cafile=named)
    except (OSError, ssl.SSLError) as error:
        return Probe("trust_store", False, f"the trust store does not load: {error}")
    return Probe("trust_store", True, "the system trust store loads")


def proxy(environ: Mapping[str, str] | None = None) -> Probe:
    """Every proxy the environment names is a URL a client can use."""
    environ = os.environ if environ is None else environ
    named = [(name, environ[name]) for name in PROXY_VARIABLES if environ.get(name)]
    for name, value in named:
        parts = urlsplit(value)
        if parts.scheme not in PROXY_SCHEMES or not parts.hostname:
            return Probe("proxy", False, f"{name} is not a proxy URL")
    return Probe("proxy", True, f"{len(named)} proxy setting(s), each a URL" if named else "none")


async def platform_and_clock(
    client: ApiClient, max_skew_seconds: float, now: Callable[[], datetime]
) -> list[Probe]:
    """The platform answers, and the host's clock is within the skew of its."""
    try:
        health = await client.health()
    # Any failure to reach the platform is the finding, whatever raised it.
    except Exception as error:
        return [
            Probe("platform", False, f"{client.base_url} does not answer: {error}"),
            Probe("clock", False, "no answer to read the platform's clock from"),
        ]
    reached = Probe("platform", health.status == "ok", f"{client.base_url}: {health.status}")
    if health.server_time is None:
        return [reached, Probe("clock", False, "the platform's answer carries no time")]
    skew = abs((now() - health.server_time).total_seconds())
    sane = skew <= max_skew_seconds
    return [reached, Probe("clock", sane, f"{skew:.0f}s from the platform's clock")]


# The metadata probe: open egress runs only where it passes.

METADATA_SERVICES: tuple[tuple[str, int], ...] = (
    ("169.254.169.254", 80),  # AWS, Azure, GCP, and most other clouds
    ("fd00:ec2::254", 80),  # AWS, over IPv6
    ("metadata.google.internal", 80),  # GCP, by its name
)
"""Where a cloud hands a machine's own credentials to whatever asks from
the machine."""

METADATA_TIMEOUT_SECONDS = 2.0
"""The longest one connection to a metadata service is waited on."""


def metadata(
    services: tuple[tuple[str, int], ...] = METADATA_SERVICES,
    connect: Callable[[tuple[str, int], float], socket.socket] = socket.create_connection,
) -> Probe:
    """No cloud metadata service answers this host. A workspace's commands
    leave from the host's own network, since a rootless engine sends a
    container's connections out as the host's user, so a service the host
    reaches is one a workspace under open egress reaches too, and it would
    hand the machine's cloud credentials to whatever the workspace runs.
    The probe passes when none of them takes a connection."""
    for host, port in services:
        try:
            connection = connect((host, port), METADATA_TIMEOUT_SECONDS)
        except OSError:
            continue
        connection.close()
        return Probe("metadata", False, f"{host}:{port} answers, so open egress is refused")
    return Probe("metadata", True, "no cloud metadata service answers")


# The isolation probes: each passes only when the mode can run here.


def run_ok(*command: str) -> bool:
    try:
        done = subprocess.run(  # a fixed command, never input
            command, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
    except OSError, subprocess.SubprocessError:
        return False
    return done.returncode == 0


def vm() -> Probe:
    """A VM per session: the kernel's virtualization device is usable, and a
    VM runner is installed."""
    usable = os.access("/dev/kvm", os.R_OK | os.W_OK)
    runner = next(
        (
            name
            for name in ("firecracker", "qemu-system-x86_64", "qemu-system-aarch64")
            if shutil.which(name)
        ),
        None,
    )
    if not usable or runner is None:
        return Probe("vm", False, "no usable /dev/kvm" if not usable else "no VM runner installed")
    return Probe("vm", True, f"/dev/kvm and {runner}")


def container() -> Probe:
    """A container per session: a container engine answers."""
    for engine in ("docker", "podman"):
        if shutil.which(engine) and run_ok(engine, "info"):
            return Probe("container", True, f"{engine} answers")
    return Probe("container", False, "no container engine answers")


def directory(workspace_user: str | None) -> Probe:
    """A directory on the host: a dedicated user exists to run it as, who is
    neither root nor the user the host runs as."""
    if not workspace_user:
        return Probe("directory", False, "no workspace user is named")
    try:
        user = pwd.getpwnam(workspace_user)
    except KeyError:
        return Probe("directory", False, f"no user {workspace_user}")
    if user.pw_uid == 0 or user.pw_uid == os.getuid():
        return Probe("directory", False, f"{workspace_user} is root or the host's own user")
    return Probe("directory", True, f"runs as {workspace_user}")


def git() -> bool:
    return run_ok("git", "--version")


@dataclass(frozen=True)
class Probes:
    """The probes a host runs, each replaceable in a test. The defaults are
    the real ones."""

    trust_store: Callable[[], Probe] = trust_store
    proxy: Callable[[], Probe] = proxy
    platform_and_clock: Callable[
        [ApiClient, float, Callable[[], datetime]], Awaitable[list[Probe]]
    ] = platform_and_clock
    metadata: Callable[[], Probe] = metadata
    isolation: Mapping[IsolationMode, Callable[[], Probe]] = field(default_factory=dict)
    capabilities: Mapping[str, Callable[[], bool]] = field(default_factory=lambda: {"git": git})


def real_probes(workspace_user: str | None) -> Probes:
    return Probes(
        isolation={
            IsolationMode.vm: vm,
            IsolationMode.container: container,
            IsolationMode.directory: lambda: directory(workspace_user),
        }
    )


@dataclass(frozen=True)
class Probed:
    """What the startup found: every probe's result, the advertisement
    built from those that passed, and whether an item may run with open
    egress here, which it may only when no cloud metadata service
    answered."""

    results: list[Probe]
    advertisement: AdvertisementBody
    open_egress: bool


async def startup(
    probes: Probes,
    client: ApiClient,
    max_skew_seconds: float,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Probed:
    """Runs every probe. A failed startup probe raises `Misconfigured`; a
    failed isolation probe leaves its mode out of the advertisement; a
    failed metadata probe keeps open egress off the host."""
    checks = [probes.trust_store(), probes.proxy()]
    checks += await probes.platform_and_clock(client, max_skew_seconds, now)
    failed = [probe for probe in checks if not probe.passed]
    if failed:
        raise Misconfigured(failed)
    modes = {mode: check() for mode, check in probes.isolation.items()}
    advertised = AdvertisementBody.model_validate(
        {
            "os": f"{platform.system()} {platform.release()}".strip()[:64] or "unknown",
            "shell": os.environ.get("SHELL", "")[:64],
            "capabilities": sorted(name for name, check in probes.capabilities.items() if check()),
            "isolation_modes": [
                mode for mode in IsolationMode if mode in modes and modes[mode].passed
            ],
        }
    )
    reach = probes.metadata()
    return Probed(
        results=[*checks, reach, *modes.values()],
        advertisement=advertised,
        open_egress=reach.passed,
    )
