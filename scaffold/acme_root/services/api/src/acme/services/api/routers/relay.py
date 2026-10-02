"""The relay's routes: a host's own calls about the `exec` items it holds.
Each is a request the host opens from inside its wall with its own
credential; the platform calls into no host. Its control stream, the one
long-lived connection it holds, is `realtime/control.py`. Each function is
one call into the relay service."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Rctx
from acme.services.api.gateway.hosts import Host
from acme.services.api.gateway.resolve import RelayService
from acme.services.api.types.relay import ExecDetailView, LeaseView, PartRequest, ResultRequest

router = APIRouter(tags=["relay"])


@router.get("/hosts/me/exec/{item_id}", response_model=ExecDetailView)
async def detail(rctx: Rctx, relay: RelayService, host: Host, item_id: UUID) -> ExecDetailView:
    """What the host runs for an item it holds: the command or the file
    operation, opened, with its deadline, its writer epoch, and where the
    workspace is."""
    return await relay.detail(rctx, host, item_id)


@router.post("/hosts/me/exec/{item_id}/parts", status_code=204)
async def push_part(
    rctx: Rctx, relay: RelayService, host: Host, item_id: UUID, body: PartRequest
) -> None:
    """One part of the item's output. A part sent again lands once."""
    await relay.push_part(rctx, host, item_id, body)


@router.post("/hosts/me/exec/{item_id}/result", status_code=204)
async def push_result(
    rctx: Rctx, relay: RelayService, host: Host, item_id: UUID, body: ResultRequest
) -> None:
    """How the item ended, stored under its call's key. The first
    settlement wins: one its lease or a stop settled already is refused."""
    await relay.push_result(rctx, host, item_id, body)


@router.post("/hosts/me/exec/{item_id}/lease", response_model=LeaseView)
async def extend(rctx: Rctx, relay: RelayService, host: Host, item_id: UUID) -> LeaseView:
    """Renews the host's lease on the item while it runs."""
    return await relay.extend(rctx, host, item_id)
