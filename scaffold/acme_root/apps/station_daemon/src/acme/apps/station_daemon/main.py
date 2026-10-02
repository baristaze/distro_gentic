"""The daemon's commands. `service-config` prints the piece of the host's
service configuration its stations' declared device access becomes, for
its owner to review line by line. `run` starts the daemon: it picks up its
credential, or trades its first one, then rotates, claims, and runs its
lab's station work until stopped. Exit codes: 0 done, 1 the platform
refused, 2 a setting or a file on the host is wrong, 3 not enrolled, 4 the
platform is unreachable at the start."""

import asyncio
import logging
import sys
from collections.abc import Coroutine
from importlib.metadata import PackageNotFoundError, version
from typing import Any, NoReturn

import httpx
import typer

from acme.apps.station_daemon import stations as owner_stations
from acme.apps.station_daemon.adapter import adapter_for
from acme.apps.station_daemon.config import BadSetting, Settings, settings_from_env
from acme.apps.station_daemon.daemon import NotEnrolled, StationDaemon
from acme.client.client import ApiClient, ApiError

EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NOT_ENROLLED = 3
EXIT_UNREACHABLE = 4


def app_version() -> str:
    try:
        return f"station-daemon@{version('acme-station-daemon')}"
    except PackageNotFoundError:
        return "station-daemon@dev"


def build_client(api_url: str, token: str | None) -> ApiClient:
    """The one place a client is built; a daemon is a machine caller, `api`."""
    return ApiClient(api_url, app="api", app_version=app_version(), token=token)


app = typer.Typer(
    help="The Acme station daemon: fence every lease, hold the owner's limits, run the stations.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


@app.command("service-config")
def service_config() -> None:
    """Print the device access the stations declare, as a systemd drop-in."""
    settings = settings_from_env()
    try:
        typer.echo(
            owner_stations.service_config(owner_stations.load(settings.stations_path)), nl=False
        )
    except BadSetting as error:
        _fail(str(error), EXIT_USAGE)


@app.command()
def run() -> None:
    """Start the daemon and serve the lab until stopped."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = settings_from_env()

    async def go() -> None:
        held = owner_stations.load(settings.stations_path)
        daemon = StationDaemon(
            settings,
            held,
            {station_id: adapter_for(station) for station_id, station in held.items()},
            lambda token: build_client(settings.api_url, token),
            version=app_version(),
        )
        await daemon.start()
        await serve(daemon, settings)

    _guarded(go())


async def serve(daemon: StationDaemon, settings: Settings) -> None:
    """Runs jobs while there are some, and waits a while when there are none
    or the platform cannot be reached."""
    while True:
        ran = await daemon.tick()
        if ran is None:
            await asyncio.sleep(settings.idle_seconds)


def _guarded(coroutine: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coroutine)
    except BadSetting as error:
        _fail(str(error), EXIT_USAGE)
    except NotEnrolled as error:
        _fail(f"not enrolled: {error}", EXIT_NOT_ENROLLED)
    except ApiError as error:
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
