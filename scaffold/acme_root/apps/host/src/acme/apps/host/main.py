"""The host's commands. `probe` runs the startup probes and prints what the
host would advertise. `run` starts the host: it probes, enrolls once or
picks up its credential, then beats, rotates, and claims until stopped,
waiting out a failure it outlasts. Exit codes: 0 done, 1 the platform
refused, 2 a setting or a file on the host is wrong, 3 not enrolled, 4 the
platform is unreachable or failing at startup, or the clock is not yet in
step with it, which passes with time, 5 a startup probe failed that a person
must fix."""

import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import Callable, Coroutine, Mapping
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Any, NoReturn

import httpx
import typer

from acme.apps.host import ceilings
from acme.apps.host.agent import HostAgent
from acme.apps.host.config import BadSetting, Settings, settings_from_env
from acme.apps.host.machine import machine_probes
from acme.apps.host.probe import Misconfigured, Probe, real_probes, snapshot_modes, startup
from acme.apps.host.relay import HOST_MODES, ExecutorRelayImpl
from acme.apps.host.seed import forget_key
from acme.apps.host.snapshots import HostSnapshots
from acme.client.claimant.enrollment import CredentialRefused, NotEnrolled
from acme.client.client import WIRE_FAILURES, ApiClient, ApiError
from acme.client.types import IsolationMode as HostIsolation
from acme.infra.exceptions import InfraException
from acme.infra.secrets.local import SecretsLocalImpl
from acme.infra.transports import CredentialBrokerInterface, TransportInterface
from acme.infra.transports.broker import BrokerNullImpl
from acme.infra.transports.container import TransportContainerImpl
from acme.infra.transports.machine import TransportMachineImpl
from acme.infra.workspaces import IsolationMode, WorkspaceProviderInterface
from acme.infra.workspaces.container import WorkspaceContainerImpl
from acme.infra.workspaces.machine import WorkspaceMachineImpl
from acme.infra.workspaces.network import HostNetwork

log = logging.getLogger(__name__)

EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NOT_ENROLLED = 3
EXIT_UNREACHABLE = 4
EXIT_MISCONFIGURED = 5


def app_version() -> str:
    try:
        return f"host@{version('acme-host')}"
    except PackageNotFoundError:
        return "host@dev"


def build_client(api_url: str, token: str | None) -> ApiClient:
    """The one place a client is built; a host is a machine caller, `api`."""
    return ApiClient(api_url, app="api", app_version=app_version(), token=token)


app = typer.Typer(
    help="The Acme workspace host: probe the machine, enroll once, claim pinned work.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


@app.command()
def probe() -> None:
    """Run the startup probes and print what this host would advertise."""
    settings = settings_from_env()

    async def go() -> None:
        probes = machine_probes() if settings.machine else real_probes(settings.workspace_user)
        async with build_client(settings.api_url, None) as client:
            probed = await startup(probes, client, settings.max_clock_skew_seconds)
        for result in probed.results:
            typer.echo(f"{'ok ' if result.passed else 'no '} {result.name}: {result.detail}")
        typer.echo(probed.advertisement.model_dump_json(exclude_none=True))

    _guarded(go())


@app.command()
def run() -> None:
    """Start the host and claim until stopped."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings_from_env()

    async def go() -> None:
        agents: list[HostAgent] = []
        workspaces = host_workspaces(settings)
        # A machine of the cloud pool keeps no snapshot store: its pool keeps
        # the machine's whole disk.
        store = (
            None
            if settings.machine
            else HostSnapshots(settings.snapshots_path, settings.secrets_path)
        )
        # One broker: what the transport attaches, a snapshot takes back.
        broker = BrokerNullImpl()
        executor = ExecutorRelayImpl(
            lambda: agents[0].client(),
            host_transports(settings, broker),
            workspaces,
            snapshots=store,
            broker=broker,
            snapshot_modes=lambda: frozenset(
                ENGINE_MODES[mode] for mode in snapshot_modes(agents[0].probed.advertisement)
            ),
            kept_whole=KEPT_WHOLE if settings.machine else frozenset(),
        )
        agent = HostAgent(
            settings,
            ceilings.load(settings.ceilings_path),
            machine_probes()
            if store is None
            else real_probes(settings.workspace_user, host_snapshots(workspaces, store)),
            lambda token: build_client(settings.api_url, token),
            executor,
        )
        agents.append(agent)
        await agent.start()
        if settings.machine_seed is not None:
            # Traded: a key is spent once.
            forget_key(settings.machine_seed)
        await serve(agent, settings)

    _guarded(go())


def host_network() -> HostNetwork:
    """This host's proxy and CA file, read as it starts. A CA file it cannot
    read stops it there, as a failed startup probe does, never at a
    session's prepare."""
    try:
        return HostNetwork.of(os.environ)
    except InfraException as error:  # its CA file, unreadable
        raise Misconfigured([Probe("trust_store", False, str(error))]) from error


def host_transports(
    settings: Settings, broker: CredentialBrokerInterface | None = None
) -> dict[IsolationMode, TransportInterface]:
    """The transports this host runs work through: a container per session,
    on its local Docker. A bare directory runs only as the host's dedicated
    user, which no transport here does yet, so an item at that mode is
    refused rather than run as the host's own user. A command under open
    egress goes through the host's proxy and trusts its CA file."""
    secrets = SecretsLocalImpl(settings.secrets_path)
    if settings.machine:
        return {
            IsolationMode.VM: TransportMachineImpl(
                settings.records_path,
                secrets,
                broker or BrokerNullImpl(),
                network=host_network(),
            )
        }
    container = TransportContainerImpl(
        settings.records_path,
        secrets,
        broker or BrokerNullImpl(),
        timedelta(seconds=30),
        host_network(),
    )
    return {IsolationMode.CONTAINER: container}


def host_workspaces(settings: Settings) -> dict[IsolationMode, WorkspaceProviderInterface]:
    """What makes a workspace its pool asks this host to prepare, by the
    mode its transport runs: a container per session, of the image its
    owner names, holding a copy of the host's CA file under open egress. A
    machine of the cloud pool makes its one session's workspace in itself."""
    if settings.machine:
        return {IsolationMode.VM: WorkspaceMachineImpl(settings.machine_workspace)}
    return {
        IsolationMode.CONTAINER: WorkspaceContainerImpl(
            settings.workspace_image,
            timedelta(seconds=30),
            f"host-{settings.name}",
            timedelta(seconds=settings.pull_timeout_seconds),
            host_network(),
        )
    }


ENGINE_MODES: dict[HostIsolation, IsolationMode] = {
    host: engine for engine, host in HOST_MODES.items()
}
"""The engine's mode a host's advertised mode names."""


def host_snapshots(
    workspaces: Mapping[IsolationMode, WorkspaceProviderInterface], store: HostSnapshots
) -> dict[HostIsolation, Callable[[], bool]]:
    """The modes whose snapshots this host keeps: each one a provider of its
    own snapshots, once its store takes one and gives it back. The
    container provider snapshots its whole filesystem; a mode with no
    provider here keeps none."""
    return {HOST_MODES[mode]: store.usable for mode in workspaces if mode in SNAPSHOTTING}


KEPT_WHOLE = frozenset({IsolationMode.VM})
"""The level a machine of the cloud pool holds a workspace kept by snapshots
at: its pool keeps the machine's whole disk, and the host takes none."""

SNAPSHOTTING = frozenset({IsolationMode.CONTAINER})
"""The engine's modes whose providers here snapshot a workspace whole: the
container's. A directory's commands write outside it, so its provider
snapshots none, and this host runs no VM."""


async def serve(agent: HostAgent, settings: Settings) -> None:
    """Claims while there is work and a free slot, waits a beat when there is
    neither, and waits out a failure the host outlasts (`HostAgent.turn`);
    the control stream, or an item that ends, cuts a wait short. Each item
    runs beside the others, so a long command holds up no other call. It
    beats and rotates its credential on a loop of its own too, so a long
    command keeps the host online and its credential live."""
    beside = [
        asyncio.ensure_future(listen(agent)),
        asyncio.ensure_future(keep_alive(agent, settings)),
    ]
    try:
        while True:
            # Cleared before the turn, so a wake that comes during it holds.
            agent.woken.clear()
            wait = await agent.turn()
            if wait > 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(agent.woken.wait(), wait)
    finally:
        for task in beside:
            task.cancel()


async def keep_alive(agent: HostAgent, settings: Settings) -> None:
    """Rotates the credential when it is due and beats, every beat."""
    while True:
        await asyncio.sleep(settings.beat_seconds)
        try:
            await agent.rotate_if_due()
            await agent.beat()
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("the beat failed: %s", error)


async def listen(agent: HostAgent) -> None:
    """The control stream, opened again whenever it ends: with the
    credential the host holds then, after a short wait that grows while the
    platform cannot be reached."""
    wait = 1.0
    while True:
        try:
            await agent.listen()
            wait = 1.0
        except (ApiError, *WIRE_FAILURES) as error:
            log.warning("the control stream ended: %s", error)
            wait = min(wait * 2, 30.0)
        await asyncio.sleep(wait)


def _guarded(coroutine: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coroutine)
    except BadSetting as error:
        _fail(str(error), EXIT_USAGE)
    except Misconfigured as error:
        if error.passes_with_time:
            _fail(f"not ready: {error}", EXIT_UNREACHABLE)
        _fail(f"misconfigured: {error}", EXIT_MISCONFIGURED)
    except NotEnrolled as error:
        _fail(f"not enrolled: {error}", EXIT_NOT_ENROLLED)
    except CredentialRefused as error:
        _fail(f"refused: {error}", EXIT_REFUSED)
    except ApiError as error:
        # An answer the platform could not serve, or a 429, passes with time,
        # as it does once the host runs (`HostAgent.turn`).
        if error.status >= 500 or error.status == 429:
            _fail(f"the platform failed: {error.status} {error}", EXIT_UNREACHABLE)
        _fail(f"refused: {error}", EXIT_REFUSED)
    except httpx.TransportError as error:
        _fail(f"cannot reach the platform: {error}", EXIT_UNREACHABLE)


def main() -> int:
    try:
        app(standalone_mode=True)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
