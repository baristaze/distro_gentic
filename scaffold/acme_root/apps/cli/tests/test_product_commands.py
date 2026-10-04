"""A product's command groups: mounted by the CLI after its own and built
with its `run`, and refused, when the CLI starts, if a name is one the CLI
holds or is declared twice."""

import importlib
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest
import typer
import typer.main
from cli_support import Stack

from acme.apps.cli import main, product_commands
from acme.apps.cli.groups import CommandGroup, Run, mount_groups
from acme.client.client import ApiClient

Start = Callable[..., ModuleType]


def reports(run: Run) -> typer.Typer:
    """A product's group: one command, a call as the signed-in person."""
    reports_app = typer.Typer(help="A product's own commands.", no_args_is_help=True)

    @reports_app.command("whoami")
    def reports_whoami() -> None:
        async def go(client: ApiClient) -> None:
            me = await client.me()
            typer.echo(f"reports sees {me.user.email}")

        run(go, None)

    return reports_app


@pytest.fixture
def start() -> Iterator[Start]:
    """Starts the CLI as `acme` does, by importing `main` afresh with the
    groups a product declares; the platform's own declaration comes back
    after the test."""
    declared = product_commands.PRODUCT_COMMANDS

    def start_with(*groups: CommandGroup) -> ModuleType:
        product_commands.PRODUCT_COMMANDS = groups
        return importlib.reload(main)

    try:
        yield start_with
    finally:
        product_commands.PRODUCT_COMMANDS = declared
        importlib.reload(main)


@pytest.fixture
def reports_declared(start: Start) -> None:
    """Asked for before `stack`, which patches the module a start imports afresh."""
    start(CommandGroup("reports", reports))


@pytest.mark.usefixtures("reports_declared")
def test_a_group_a_product_declares_is_mounted_and_runs_as_the_signed_in_person(
    stack: Stack,
) -> None:
    listed = stack.acme("--help")
    assert listed.exit_code == 0 and "reports " in listed.output and "session " in listed.output
    assert stack.acme("reports", "whoami").output == "reports sees ann@example.test\n"
    # The group is built with the CLI's own `run`, so it signs in the way
    # every command does, and the platform's commands stand beside it.
    refused = stack.acme("reports", "whoami", token=None)
    assert refused.exit_code == main.EXIT_NOT_SIGNED_IN
    assert "not signed in" in refused.output
    assert stack.acme("whoami").exit_code == 0


PLATFORM_NAMES = sorted(typer.main.get_group(main.app).commands)


def test_the_platform_holds_the_names_the_refusal_below_runs_over() -> None:
    # A group, `session`, and a command, `login`: each name at the top is taken.
    assert {"session", "project", "automation", "login", "listen"} <= set(PLATFORM_NAMES)


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_a_group_reusing_a_platform_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=f"command group {name} is the platform's"):
        mount_groups(main.app, [CommandGroup(name, reports)], main.run)


def test_the_cli_refuses_to_start_on_a_group_reusing_a_platform_name(start: Start) -> None:
    with pytest.raises(ValueError, match="command group session is the platform's"):
        start(CommandGroup("session", reports))


def test_a_name_declared_twice_is_refused_and_nothing_is_mounted() -> None:
    app = typer.Typer()
    app.command("ping")(lambda: None)

    with pytest.raises(ValueError, match="command group reports is declared twice"):
        mount_groups(
            app, [CommandGroup("reports", reports), CommandGroup("reports", reports)], main.run
        )
    assert app.registered_groups == []
