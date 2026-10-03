"""The scripted provider: the twin of every model provider. It answers each
call with the next turn of its script, streamed in parts and ending in the
reply with its usage, or fails with the turn's error kind, before the
stream or after part of it. So every suite runs offline and the same way
twice, and a session's recorded replies can drive it again.

It stands in for one provider at a time, by name, and is refused at boot
in a deployed environment, like every twin."""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from pathlib import Path

from pydantic import Field, SecretStr, TypeAdapter

from acme.infra.base import InfraModel, thaw_mapping
from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.calls import (
    Finished,
    ModelCall,
    ModelReply,
    StreamPart,
    TextDelta,
    ThinkingDelta,
    ToolUseDelta,
)
from acme.integrations.model_providers.content import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from acme.integrations.model_providers.failures import ModelCallFailed
from acme.integrations.model_providers.types import ErrorKind, ProviderName

CHUNK = 16
"""The most characters one scripted part carries, so a reply streams in
several parts the way a provider's does."""


class ScriptedFailure(InfraModel):
    """A turn that fails with its kind. With a `partial`, the stream first
    delivers it and then breaks, failing with it as what arrived."""

    kind: ErrorKind
    message: str = "scripted failure"
    status: int | None = None
    retry_after: float | None = Field(default=None, ge=0)
    partial: ModelReply | None = None


Turn = ModelReply | ScriptedFailure
"""One turn of a script: the reply a call gets, or the failure it meets."""

SCRIPT = TypeAdapter(dict[ProviderName, list[Turn]])
"""A script as a file holds it: each provider's turns, in the order its
calls take them."""


LAST_RESULT = "$last_result."
"""A tool input's value `$last_result.<field>` is answered at the call by
that field of the JSON object the call's last tool result holds: a script
written before the run cites what a tool answers in it, such as the ids of
the runs a validation wrote. A value with no such field stays as written."""


def last_result(call: ModelCall) -> dict[str, object] | None:
    """The JSON object the call's last tool result holds, or None when its
    text is not one."""
    for message in reversed(call.messages):
        for block in reversed(message.blocks):
            if isinstance(block, ToolResultBlock):
                text = "".join(part.text for part in block.parts if isinstance(part, TextBlock))
                try:
                    found = json.loads(text)
                except ValueError:
                    return None
                return found if isinstance(found, dict) else None
    return None


def filled(reply: ModelReply, call: ModelCall) -> ModelReply:
    """The reply with each `$last_result.<field>` input answered (`LAST_RESULT`)."""
    fields = last_result(call)
    if fields is None:
        return reply

    def value(given: object) -> object:
        if isinstance(given, str) and given.startswith(LAST_RESULT):
            return fields.get(given.removeprefix(LAST_RESULT), given)
        return given

    blocks = tuple(
        ToolUseBlock(
            id=block.id,
            name=block.name,
            input={key: value(given) for key, given in thaw_mapping(block.input).items()},
        )
        if isinstance(block, ToolUseBlock)
        else block
        for block in reply.blocks
    )
    return reply.model_copy(update={"blocks": blocks})


def read_script(path: Path) -> dict[ProviderName, list[Turn]]:
    """The script a process's twin answers from, read once at boot from a
    JSON file: an object of provider names, each a list of turns."""
    return SCRIPT.validate_json(path.read_bytes())


def _chunks(text: str) -> list[str]:
    return [text[i : i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]


def parts_of(reply: ModelReply) -> list[StreamPart]:
    """The parts a provider would stream for `reply`: its turn in order,
    each block in pieces, indexed by its place in the turn. The last
    `Finished` is the caller's to add."""
    parts: list[StreamPart] = []
    for index, block in enumerate(reply.turn()):
        if isinstance(block, ThinkingBlock):
            parts.extend(ThinkingDelta(index=index, text=piece) for piece in _chunks(block.text))
        elif isinstance(block, TextBlock):
            parts.extend(TextDelta(index=index, text=piece) for piece in _chunks(block.text))
        elif isinstance(block, ToolUseBlock):
            text = json.dumps(thaw_mapping(block.input), separators=(",", ":"), sort_keys=True)
            parts.append(ToolUseDelta(index=index, id=block.id, name=block.name))
            parts.extend(
                ToolUseDelta(index=index, id=block.id, name=block.name, partial_input=piece)
                for piece in _chunks(text)
            )
    return parts


class ModelProviderScriptedImpl(ModelProviderInterface):
    def __init__(
        self,
        provider: ProviderName,
        script: Sequence[ModelReply | ScriptedFailure] = (),
        *,
        pace: timedelta = timedelta(0),
    ) -> None:
        self._provider = provider
        self._script: deque[ModelReply | ScriptedFailure] = deque(script)
        # The wait before each part, so a stream stays open long enough to
        # watch; zero streams at once.
        self._pace = pace.total_seconds()
        self.calls: list[ModelCall] = []
        """Every call it was asked, in order, for a test to read."""

    @property
    def provider(self) -> ProviderName:
        return self._provider

    def add(self, *turns: ModelReply | ScriptedFailure) -> None:
        """More turns at the end of the script."""
        self._script.extend(turns)

    @property
    def remaining(self) -> int:
        return len(self._script)

    async def stream(
        self, call: ModelCall, *, credential: SecretStr | None = None
    ) -> AsyncIterator[StreamPart]:
        self.calls.append(call)
        if not self._script:
            raise ModelCallFailed(ErrorKind.PERMANENT, "the script holds no turn for this call")
        turn = self._script.popleft()
        if isinstance(turn, ScriptedFailure):
            if turn.partial is not None:
                for part in parts_of(turn.partial):
                    yield part
            raise ModelCallFailed(
                turn.kind,
                turn.message,
                status=turn.status,
                retry_after=turn.retry_after,
                partial=turn.partial,
            )
        turn = filled(turn, call)
        for part in parts_of(turn):
            if self._pace:
                await asyncio.sleep(self._pace)
            yield part
        yield Finished(reply=turn)

    def describe(self) -> str:
        return f"model provider {self._provider.value}: the scripted twin, {len(self._script)} turn(s) left"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
