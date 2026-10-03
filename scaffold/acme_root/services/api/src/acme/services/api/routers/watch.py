"""The watch's routes: a live read of a session's open streams, and of an
item's streams of a product's kind, and take control, a command by hand,
and give back. A read is served by its handle alone, the way a presigned
URL is, and it reads; nothing is pushed. Each function is one call into
the watch service."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from acme.om.watch.kinds import STREAM_KIND
from acme.om.watch.rules import MAX_HANDLE
from acme.services.api.gateway.auth import Ctx, Rctx
from acme.services.api.gateway.idempotency import Idem
from acme.services.api.gateway.resolve import WatchService
from acme.services.api.types.agent_sessions import AgentSessionView
from acme.services.api.types.watch import (
    CommandProgressView,
    CommandRequest,
    GiveBackRequest,
    HandRunView,
    ItemPageView,
    ItemReadView,
    LivePageView,
    LiveReadView,
)

router = APIRouter(tags=["watch"])


@router.post("/agent-sessions/{session_id}/live", response_model=LiveReadView)
async def open_live(ctx: Ctx, watch: WatchService, session_id: UUID) -> LiveReadView:
    """A handle to the session's open streams, for a viewer who may read it,
    that lasts minutes."""
    return await watch.open_live(ctx, session_id)


@router.get("/live", response_model=LivePageView)
async def read_live(
    rctx: Rctx,
    watch: WatchService,
    handle: Annotated[str, Query(min_length=1, max_length=MAX_HANDLE)],
    after: Annotated[list[str] | None, Query()] = None,
) -> LivePageView:
    """The open streams of the handle's session, each after the last part
    read (`after=<step_id>:<last>`, once a stream, the `last` of that part).
    The handle is the authority: one that does not verify, or has expired,
    reads nothing."""
    return await watch.read_live(rctx, handle, after or [])


@router.post("/work-items/{item_id}/streams/{kind}/live", response_model=ItemReadView)
async def open_item_live(
    ctx: Ctx,
    watch: WatchService,
    item_id: UUID,
    kind: Annotated[str, Path(pattern=STREAM_KIND.pattern)],
) -> ItemReadView:
    """A handle to the item's open streams of a kind a product's claimant
    writes, for a viewer who may read its tenant, that lasts minutes."""
    return await watch.open_item_live(ctx, item_id, kind)


@router.get("/live/items", response_model=ItemPageView)
async def read_item_live(
    rctx: Rctx,
    watch: WatchService,
    handle: Annotated[str, Query(min_length=1, max_length=MAX_HANDLE)],
    after: Annotated[list[str] | None, Query()] = None,
) -> ItemPageView:
    """The open streams the handle names, each after the last entry read
    (`after=<stream>:<last>`, once a stream). The handle is the authority:
    one that does not verify as an item's, or has expired, reads nothing."""
    return await watch.read_item_live(rctx, handle, after or [])


@router.post("/agent-sessions/{session_id}/control", response_model=AgentSessionView)
async def take_control(ctx: Ctx, watch: WatchService, session_id: UUID) -> AgentSessionView:
    """The person takes the session's environment: the agent stands down,
    its loop parked on a hand-over."""
    return await watch.take_control(ctx, session_id)


@router.post(
    "/agent-sessions/{session_id}/control/commands", response_model=HandRunView, status_code=201
)
async def run_command(
    ctx: Ctx, watch: WatchService, session_id: UUID, body: CommandRequest, idem: Idem
) -> Response:
    """A command by hand, recorded as the person's run and sent to the host
    that holds the workspace. A retried send is the same run."""
    return await idem.run(
        201, lambda attempt: watch.run_command(ctx, session_id, body, attempt.target_id)
    )


@router.get(
    "/agent-sessions/{session_id}/control/commands/{key}", response_model=CommandProgressView
)
async def command(
    ctx: Ctx,
    watch: WatchService,
    session_id: UUID,
    key: UUID,
    after_seq: Annotated[int, Query(ge=-1)] = -1,
) -> CommandProgressView:
    """How the command stands: its output after `after_seq`, and how it
    ended once it has."""
    return await watch.command(ctx, session_id, key, after_seq)


@router.post("/agent-sessions/{session_id}/control/give-back", response_model=AgentSessionView)
async def give_back(
    ctx: Ctx, watch: WatchService, session_id: UUID, body: GiveBackRequest
) -> AgentSessionView:
    """The person gives the environment back: their summary is the message
    the agent reads on resume. A command of theirs still running refuses it,
    unless `stop` asks it stopped first."""
    return await watch.give_back(ctx, session_id, body)
