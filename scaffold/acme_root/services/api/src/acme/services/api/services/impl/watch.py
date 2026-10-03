from collections.abc import Sequence
from uuid import UUID

from acme.om.context import RequestContext, TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.steps.types.stream import StreamPart, TextPart, ThinkingPart, ToolInputPart
from acme.om.watch import WatchManagerInterface
from acme.om.watch.types.control import HandCommand
from acme.om.watch.types.live import MAX_SEEN, Seen
from acme.services.api.services.impl.agent_sessions import session_view
from acme.services.api.services.watch import WatchServiceInterface
from acme.services.api.types.agent_sessions import AgentSessionView
from acme.services.api.types.watch import (
    CommandPartView,
    CommandProgressView,
    CommandRequest,
    GiveBackRequest,
    HandRunView,
    LivePageView,
    LivePartView,
    LiveReadView,
    LiveStreamView,
    PartKind,
)


def seen_of(after: Sequence[str]) -> tuple[Seen, ...]:
    """Each `<step_id>:<last>` a reader names, read; anything else is refused."""
    if len(after) > MAX_SEEN:
        raise ValidationFailed(f"a read names at most {MAX_SEEN} streams")
    seen: list[Seen] = []
    for mark in after:
        step, _, n = mark.partition(":")
        try:
            seen.append(Seen(step_id=UUID(step), n=int(n)))
        except ValueError:
            raise ValidationFailed(f"{mark[:80]!r} is not <step_id>:<last>") from None
    return tuple(seen)


def part_view(part: StreamPart) -> LivePartView:
    view = LivePartView(kind=PartKind(part.kind), n=part.n, last=part.end, text=part.text)
    if isinstance(part, TextPart | ThinkingPart):
        return view.model_copy(update={"index": part.index})
    if isinstance(part, ToolInputPart):
        return view.model_copy(
            update={"index": part.index, "tool_use_id": part.tool_use_id, "tool": part.tool}
        )
    return view.model_copy(update={"channel": part.channel})


class WatchServiceImpl(WatchServiceInterface):
    def __init__(self, watch: WatchManagerInterface) -> None:
        self._watch = watch

    async def open_live(self, ctx: TenantContext, session_id: UUID) -> LiveReadView:
        live = await self._watch.open_live(ctx, session_id)
        return LiveReadView(
            session_id=live.session_id, handle=live.handle, expires_at=live.expires_at
        )

    async def read_live(
        self, rctx: RequestContext, handle: str, after: Sequence[str]
    ) -> LivePageView:
        page = await self._watch.read_live(rctx, handle, seen_of(after))
        return LivePageView(
            session_id=page.session_id,
            streams=[
                LiveStreamView(
                    step_id=stream.step_id,
                    first=stream.first,
                    dropped=stream.dropped,
                    parts=[part_view(part) for part in stream.parts],
                )
                for stream in page.streams
            ],
        )

    async def take_control(self, ctx: TenantContext, session_id: UUID) -> AgentSessionView:
        return session_view(await self._watch.take_control(ctx, session_id))

    async def run_command(
        self, ctx: TenantContext, session_id: UUID, body: CommandRequest, key: UUID
    ) -> HandRunView:
        command = HandCommand(
            key=key, argv=tuple(body.argv), cwd=body.cwd, timeout_seconds=body.timeout_seconds
        )
        run = await self._watch.run_command(ctx, session_id, command)
        return HandRunView(
            item_id=run.item_id,
            session_id=run.session_id,
            command_key=run.key,
            user_id=run.user_id,
            epoch=run.epoch,
            state=run.state,
        )

    async def command(
        self, ctx: TenantContext, session_id: UUID, key: UUID, after_seq: int
    ) -> CommandProgressView:
        progress = await self._watch.command(ctx, session_id, key, after_seq)
        view = CommandProgressView(
            state=progress.state,
            parts=[
                CommandPartView(seq=part.seq, stream=part.stream, text=part.text)
                for part in progress.parts
            ],
        )
        if progress.outcome is not None:
            outcome = progress.outcome
            view = view.model_copy(
                update={
                    "exit_code": outcome.exit_code,
                    "timed_out": outcome.timed_out,
                    "truncated": outcome.truncated,
                    "stopped": outcome.stopped,
                    "refused": outcome.refused,
                }
            )
        if progress.output is not None:
            view = view.model_copy(
                update={"stdout": progress.output.stdout, "stderr": progress.output.stderr}
            )
        return view

    async def give_back(
        self, ctx: TenantContext, session_id: UUID, body: GiveBackRequest
    ) -> AgentSessionView:
        return session_view(await self._watch.give_back(ctx, session_id, body.summary, body.stop))
