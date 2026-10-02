"""Take control: a command a person runs in a session's workspace while
the agent stands down, and the run it is recorded as. What the command runs
and prints is the session's content, sealed in the relay's item; what is
here stays in the clear."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from acme.om.base import Platform
from acme.om.relay.types.exec import ExecState

MAX_ARGS = 256
MAX_ARG = 4096
MAX_TIMEOUT = 3600


class HandCommand(Platform):
    """A command a person runs by hand: its key, which a retry sends again
    so the command runs once, what it runs, where in the workspace, and how
    long it may take."""

    key: UUID
    argv: tuple[Annotated[str, Field(min_length=1, max_length=MAX_ARG)], ...] = Field(
        min_length=1, max_length=MAX_ARGS
    )
    cwd: str = Field(default=".", min_length=1, max_length=MAX_ARG)
    timeout_seconds: int = Field(default=300, gt=0, le=MAX_TIMEOUT)


class HandRun(Platform):
    """A person's command as it was recorded: the relay's item, which holds
    what ran and how it ended, the person it is attributed to, and the
    writer epoch it runs under."""

    item_id: UUID
    session_id: UUID
    key: UUID
    user_id: UUID
    epoch: int = Field(ge=0)
    state: ExecState
