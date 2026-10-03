"""The wire types of the watch: a live-read handle and what it reads, and
take control, a command by hand, and its progress. A part's text is the
session's content, read by whoever holds the handle until it expires."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field

from acme.om.relay.types.exec import ExecState, StopKind
from acme.om.watch.types.control import MAX_ARG, MAX_ARGS, MAX_TIMEOUT
from acme.services.api.types.agent_sessions import MAX_MESSAGE
from acme.services.api.types.common import RequestBody, View


class LiveReadView(View):
    """A handle to one session's open streams until `expires_at`. Read it
    at `GET /v1/live?handle=`; a viewer asks for a new one when it ends."""

    session_id: UUID
    handle: str
    expires_at: datetime


class PartKind(StrEnum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_INPUT = "tool_input"
    TOOL_OUTPUT = "tool_output"


class LivePartView(View):
    """One part of a stream: its kind, its place, and its text. `index` is
    the block of a model response it belongs to; a tool call's input names
    the call, and a tool's output its channel."""

    kind: PartKind
    n: int
    text: str
    index: int | None = None
    tool_use_id: str | None = None
    tool: str | None = None
    channel: str | None = None


class LiveStreamView(View):
    """One open stream: the step it adds up to, the oldest part the service
    still holds, the parts after the last one read, and whether parts never
    read were let go. The step holds them once it is stored."""

    step_id: UUID
    first: int
    dropped: bool
    parts: list[LivePartView]


class LivePageView(View):
    session_id: UUID
    streams: list[LiveStreamView]


class CommandRequest(RequestBody):
    """A command by hand: what it runs, where in the workspace, and how long
    it may take. Its key is the request's idempotency key."""

    argv: list[Annotated[str, Field(min_length=1, max_length=MAX_ARG)]] = Field(
        min_length=1, max_length=MAX_ARGS
    )
    cwd: str = Field(default=".", min_length=1, max_length=MAX_ARG)
    timeout_seconds: int = Field(default=300, gt=0, le=MAX_TIMEOUT)


class HandRunView(View):
    """A command by hand as recorded: the item that holds what ran, the
    person it is attributed to, and the writer epoch it runs under."""

    item_id: UUID
    session_id: UUID
    command_key: UUID
    user_id: UUID
    epoch: int
    state: ExecState


class CommandPartView(View):
    seq: int
    stream: str
    text: str


class CommandProgressView(View):
    """How a command stands: its state, its output after the last part read,
    and how it ended once it has. `refused` names why its host or the relay
    refused it, such as a command a later run fenced."""

    state: ExecState
    parts: list[CommandPartView]
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    stopped: StopKind | None = None
    refused: str | None = None
    stdout: str | None = None
    stderr: str | None = None


class GiveBackRequest(RequestBody):
    """What the person did, as the agent reads it on resume."""

    summary: str = Field(min_length=1, max_length=MAX_MESSAGE)
    # A command of the person's still running refuses the giving back,
    # unless this asks it stopped first.
    stop: bool = False
