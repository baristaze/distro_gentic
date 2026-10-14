"""The exec relay's routes: a host's own calls about the `exec` items it holds,
and its answers to a workspace it was asked to prepare or to release.
Each is a request the host opens from inside its wall with its own
credential; the platform calls into no host. Its control stream, the one
long-lived connection it holds, is `realtime/control.py`. Each function is
one call into the exec relay service."""

from uuid import UUID

from fastapi import APIRouter

from acme.services.api.gateway.auth import Rctx
from acme.services.api.gateway.hosts import Host
from acme.services.api.gateway.resolve import ExecRelayService
from acme.services.api.types.exec_relay import (
    ExecDetailView,
    ExecLeaseView,
    PartRequest,
    PreparedView,
    PrepareRequest,
    ResultRequest,
    SnapshotRequest,
)

router = APIRouter(tags=["exec_relay"])


@router.get("/hosts/me/exec/{item_id}", response_model=ExecDetailView)
async def detail(rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID) -> ExecDetailView:
    """What the host runs for an item it holds: the command or the file
    operation, opened, with its deadline, its writer epoch, and where the
    workspace is."""
    return await relay.detail(rctx, host, item_id)


@router.post("/hosts/me/exec/{item_id}/parts", status_code=204)
async def push_part(
    rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID, body: PartRequest
) -> None:
    """One part of the item's output. A part sent again lands once."""
    await relay.push_part(rctx, host, item_id, body)


@router.post("/hosts/me/exec/{item_id}/result", status_code=204)
async def push_result(
    rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID, body: ResultRequest
) -> None:
    """How the item ended, stored under its call's key. The first
    settlement wins: one its lease or a stop settled already is refused."""
    await relay.push_result(rctx, host, item_id, body)


@router.post("/hosts/me/exec/{item_id}/lease", response_model=ExecLeaseView)
async def extend(rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID) -> ExecLeaseView:
    """Renews the host's lease on the item while it runs."""
    return await relay.extend(rctx, host, item_id)


@router.post("/hosts/me/workspaces/{item_id}", response_model=PreparedView)
async def prepared(
    rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID, body: PrepareRequest
) -> PreparedView:
    """The host's answer to a prepare it claimed: where the workspace it made
    is, which binds the session to it, or why it made none, which hands the
    work back to its pool after a wait."""
    return await relay.prepared(rctx, host, item_id, body)


@router.post("/hosts/me/workspaces/{item_id}/released", status_code=204)
async def released(rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID) -> None:
    """The host's answer to a release, a purge, or an erase it claimed: what
    it names is gone. A release keeps the workspace's files on the host; a
    purge keeps none, and an erase lets the session's snapshots go from the
    host's store."""
    await relay.released(rctx, host, item_id)


@router.post("/hosts/me/workspaces/{item_id}/snapshot", status_code=204)
async def snapshotted(
    rctx: Rctx, relay: ExecRelayService, host: Host, item_id: UUID, body: SnapshotRequest
) -> None:
    """The host's answer to a snapshot it claimed: kept in its own store, by
    the reference the store knows it by and the digest of its bytes, which
    the platform records, never the bytes; or why it kept none."""
    await relay.snapshotted(rctx, host, item_id, body)
