"""How the CLI mounts the command groups a product declares
(`product_commands.PRODUCT_COMMANDS`), so a product never edits `main.py`.
A group is a name and the function that builds its commands from the
CLI's own `run`, which signs the client in and turns a refusal into an
exit code. A name the CLI already holds, a group's or a command's, is
refused, and so is a name declared twice: a product adds commands and
never replaces one of the platform's."""

from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import Any

import typer
import typer.main

from acme.client.client import ApiClient

Run = Callable[[Callable[[ApiClient], Coroutine[Any, Any, None]], str | None], None]
"""`main.run`, as a group's commands take it."""


@dataclass(frozen=True)
class CommandGroup:
    """One group of a product's commands, mounted as `<cli> <name> ...`."""

    name: str
    build: Callable[[Run], typer.Typer]


def mount_groups(app: typer.Typer, groups: Iterable[CommandGroup], run: Run) -> None:
    """Mounts each group on `app`, built with `run`. Called once, after the
    platform's own commands and groups are in `app`, so every name of
    theirs is taken. Raises `ValueError` for a name that is taken or
    declared twice, which ends the CLI's start."""
    declared = tuple(groups)
    if not declared:
        return
    taken = set(typer.main.get_group(app).commands)
    product: set[str] = set()
    for group in declared:
        if group.name in product:
            raise ValueError(f"command group {group.name} is declared twice")
        if group.name in taken:
            raise ValueError(f"command group {group.name} is the platform's")
        product.add(group.name)
    for group in declared:
        app.add_typer(group.build(run), name=group.name)
