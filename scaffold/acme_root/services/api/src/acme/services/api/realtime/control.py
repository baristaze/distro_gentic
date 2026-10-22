"""A host's control stream: the one long-lived connection a workspace host
holds, opened from inside its tenant's wall with its own credential, never
from the platform. It carries a wake when work reaches the host's lanes and
each stop of an item it holds as it is made, one JSON line a message, and a
ping while nothing happens. It ends after a minute, or with the credential
it was opened with; the host opens the next with the credential it holds
then, so a credential rotated or revoked meanwhile is met at that open.
The items stay the record: a host that reconnects after `after` is told
again what it missed.

A product's claimant holds one the same way, with its own credential
(`claimants`): a wake when work of its kinds reaches its lanes, a revoke of
each item it no longer holds under its claim, and a wake to read when a
stream its kind reads gains entries for an item it holds. It carries none
of the exec relay's messages. The queue stays the record: the stream reads
what the claimant holds again on a short timer, and the items it names as
it opens are checked at its first read."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from acme.services.api.gateway.auth import Rctx
from acme.services.api.gateway.hosts import Claimant, Host
from acme.services.api.gateway.platform_resolve import ExecRelayService, HostsService
from acme.services.api.types.exec_relay import ControlView
from acme.services.api.types.hosts import CONTROL_ITEMS, ClaimantControlView

router = APIRouter(tags=["exec_relay"])

claimants = APIRouter(tags=["hosts"])

MEDIA_TYPE = "application/x-ndjson"


@router.get(
    "/hosts/me/control",
    response_class=StreamingResponse,
    responses={200: {"model": ControlView, "content": {MEDIA_TYPE: {}}}},
)
async def control(
    rctx: Rctx, exec_relay: ExecRelayService, host: Host, after: UUID | None = None
) -> StreamingResponse:
    """The host's control stream, after the message `after` names."""

    async def lines() -> AsyncIterator[str]:
        async for message in exec_relay.control(rctx, host, after):
            yield message.model_dump_json(exclude_none=True) + "\n"

    return StreamingResponse(lines(), media_type=MEDIA_TYPE)


@claimants.get(
    "/claimants/me/control",
    response_class=StreamingResponse,
    responses={200: {"model": ClaimantControlView, "content": {MEDIA_TYPE: {}}}},
)
async def claimant_control(
    rctx: Rctx,
    hosts: HostsService,
    claimant: Claimant,
    item: Annotated[list[UUID] | None, Query(max_length=CONTROL_ITEMS)] = None,
) -> StreamingResponse:
    """The claimant's control stream. `item` names each item it works on
    now, once each: one it no longer holds is revoked at the first read."""

    async def lines() -> AsyncIterator[str]:
        async for message in hosts.control(rctx, claimant, item or []):
            yield message.model_dump_json(exclude_none=True) + "\n"

    return StreamingResponse(lines(), media_type=MEDIA_TYPE)
