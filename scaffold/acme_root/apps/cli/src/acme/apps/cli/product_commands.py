"""What this product adds to the platform's commands, declared once: its
command groups (`groups.CommandGroup`), each a name and the function that
builds its commands from the CLI's `run`. `main` mounts them after its own,
and a name the CLI already holds is refused when it starts. The platform's
own adds nothing."""

from acme.apps.cli.groups import CommandGroup

PRODUCT_COMMANDS: tuple[CommandGroup, ...] = ()
