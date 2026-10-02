"""The host's commands. `probe` runs the startup probes and prints what the
host would advertise. `run` starts the host: it probes, enrolls once or
picks up its credential, then beats, rotates, and claims until stopped.
Exit codes: 0 done, 1 the platform refused, 2 a setting or a file on the
host is wrong, 3 not enrolled, 4 the platform is unreachable, 5 a startup
probe failed."""

import asyncio
import logging
import sys
from collections.abc import Coroutine
from importlib.metadata import PackageNotFoundError, version
from typing import Any, NoReturn

import httpx
import typer

from acme.apps.host import ceilings
from acme.apps.host.agent import HostAgent, NotEnrolled
from acme.apps.host.config import BadSetting, Settings, settings_from_env
from acme.apps.host.probe import Misconfigured, real_probes, startup
from acme.client.client import ApiClient, ApiError

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
        async with build_client(settings.api_url, None) as client:
            probed = await startup(
                real_probes(settings.workspace_user), client, settings.max_clock_skew_seconds
            )
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
        agent = HostAgent(
            settings,
            ceilings.load(settings.ceilings_path),
            real_probes(settings.workspace_user),
            lambda token: build_client(settings.api_url, token),
        )
        await agent.start()
        await serve(agent, settings)

    _guarded(go())


async def serve(agent: HostAgent, settings: Settings) -> None:
    """Claims while there is work, and waits a beat when there is none."""
    while True:
        handled = await agent.tick()
        if handled is None:
            await asyncio.sleep(settings.beat_seconds)


def _guarded(coroutine: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coroutine)
    except BadSetting as error:
        _fail(str(error), EXIT_USAGE)
    except Misconfigured as error:
        _fail(f"misconfigured: {error}", EXIT_MISCONFIGURED)
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
