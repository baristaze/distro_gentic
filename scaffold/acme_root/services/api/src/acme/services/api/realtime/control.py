"""A host's control stream: the one long-lived connection a workspace host
holds, opened from inside its tenant's wall with its own credential, never
from the platform. It carries a wake when work reaches the host's lanes and
each stop of an item it holds as it is made, one JSON line a message, and a
ping while nothing happens. It ends with the credential it was opened with,
or when that credential is revoked; the host opens it again with the next.
The items stay the record: a host that reconnects after `after` is told
again what it missed."""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from acme.services.api.gateway.auth import Rctx
from acme.services.api.gateway.hosts import Host, HostBearer
from acme.services.api.gateway.resolve import RelayService
from acme.services.api.types.relay import ControlView

router = APIRouter(tags=["relay"])

MEDIA_TYPE = "application/x-ndjson"


@router.get(
    "/hosts/me/control",
    response_class=StreamingResponse,
    responses={200: {"model": ControlView, "content": {MEDIA_TYPE: {}}}},
)
async def control(
    rctx: Rctx, relay: RelayService, host: Host, credential: HostBearer, after: UUID | None = None
) -> StreamingResponse:
    """The host's control stream, after the message `after` names."""

    async def lines() -> AsyncIterator[str]:
        async for message in relay.control(rctx, host, credential, after):
            yield message.model_dump_json(exclude_none=True) + "\n"

    return StreamingResponse(lines(), media_type=MEDIA_TYPE)
