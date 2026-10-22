"""A product's claimant built from the claimant kit, holding its control
stream open over the live app in memory, the app's answer handed over as
it is sent: a `scan` job on a `scanner` pool, and the `scan_cues` its
kind reads. With the kit's idle wait at 30 s, work is claimed within a
second of landing; a lease the sweep takes back is revoked on the stream
within its re-read, never at a renewal; an append to a stream its kind
reads wakes the work within a second; and the stream ends once the
claimant is revoked, whose credential then opens none."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from api_support import build_container, seed_request
from fastapi import FastAPI
from host_support import Streamed
from test_claimant_kit_api import (
    PRODUCT as SCANNING,
)
from test_claimant_kit_api import (
    SCANNER,
    a_pool_token,
    a_scan,
    client_for,
    settings,
    tenant_of,
)

from acme.client.claimant.claimant import Claimant
from acme.client.claimant.enrollment import CredentialRefused
from acme.client.types.hosts import ClaimantControlKind, ClaimantWorkView
from acme.client.types.placement import ReportOutcome
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.om.watch.kinds import StreamKind
from acme.om.watch.root import build_kind_streams
from acme.services.api.container import AppContainer

CUES = "scan_cues"
PRODUCT = ProductKinds(
    work=SCANNING.work,
    claimants=SCANNING.claimants,
    streams=(StreamKind(CUES, entries=8, bytes=4096, streams=2, reader=SCANNER),),
)
REREAD = 5.0  # the stream's re-read of what the claimant holds


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test root, with the product's kinds and its cues registered;
    the `app`, `client`, and `owner` fixtures run over it."""
    return build_container(tmp_path, ports=PlatformPorts(kinds=PRODUCT))


@dataclass
class Counted(httpx.AsyncBaseTransport):
    """The app, its answer streamed, counting the calls a claimant makes by
    their path's last part: `claims`, `lease`, `control`."""

    inner: httpx.AsyncBaseTransport
    calls: list[str] = field(default_factory=list[str])

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path.rsplit("/", 1)[-1])
        return await self.inner.handle_async_request(request)


@pytest.fixture
def transport(app: FastAPI) -> Counted:
    return Counted(Streamed(app))


async def a_claimant(
    client: httpx.AsyncClient, owner: dict[str, str], transport: Counted, home: Path
) -> tuple[Claimant, str]:
    pool_id, token = await a_pool_token(client, owner)
    claimant = Claimant(settings(home, token), client_for(transport))
    await claimant.start()
    return claimant, pool_id


async def serve(claimant: Claimant, handed: asyncio.Queue[tuple[ClaimantWorkView, float]]) -> None:
    """The loop of the client's README, each item handed on the moment it
    is claimed and done at once."""
    async with claimant.listening():
        while True:
            turn = await claimant.turn()
            if turn.item is not None:
                handed.put_nowait((turn.item, time.monotonic()))
                await claimant.report(turn.item, ReportOutcome.done)
            await claimant.wait(turn.wait)


async def heard_open(claimant: Claimant) -> None:
    """Until the stream's first line, its wake at the open, is heard."""
    async with asyncio.timeout(5):
        await claimant.woken.wait()
    claimant.woken.clear()


async def test_work_on_its_lane_is_claimed_within_a_second_with_its_idle_wait_at_thirty(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    transport: Counted,
    tmp_path: Path,
) -> None:
    claimant, pool_id = await a_claimant(client, owner, transport, tmp_path)
    assert settings(tmp_path, None).beat_seconds == 30.0
    handed: asyncio.Queue[tuple[ClaimantWorkView, float]] = asyncio.Queue()
    loop = asyncio.ensure_future(serve(claimant, handed))
    try:
        # It opened its stream, claimed at its wake, found nothing, and now
        # waits out its idle wait.
        await asyncio.sleep(1.0)
        claims = transport.calls.count("claims")
        landed = time.monotonic()
        scan = await a_scan(container, owner, pool_id)
        item, claimed_at = await asyncio.wait_for(handed.get(), timeout=5)
        assert item.id == scan.id
        assert claimed_at - landed < 1.0, claimed_at - landed
        assert transport.calls.count("claims") == claims + 1
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)


async def test_a_lease_the_sweep_takes_back_is_revoked_on_the_stream_within_its_reread(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    transport: Counted,
    tmp_path: Path,
) -> None:
    claimant, pool_id = await a_claimant(client, owner, transport, tmp_path)
    async with claimant.listening():
        await heard_open(claimant)
        scan = await a_scan(container, owner, pool_id)
        turn = await claimant.turn()
        assert turn.item is not None and turn.item.id == scan.id
        revoked = claimant.revoked(turn.item)
        await asyncio.sleep(1.0)  # its work runs, and the stream read what it holds
        assert not revoked.is_set()

        # Its lease lapsed and the sweep took the item back.
        ctx = await tenant_of(container, owner)
        claimed = await container.managers.work.get_item(ctx, scan.id)
        await container.managers.work.extend_lease(ctx, claimed, timedelta(seconds=-1))
        renewals = transport.calls.count("lease")
        taken = time.monotonic()
        assert await container.managers.work.requeue_stale(seed_request(), 10) == 1
        async with asyncio.timeout(REREAD + 1):
            await revoked.wait()
        assert time.monotonic() - taken <= REREAD + 0.5
        assert transport.calls.count("lease") == renewals, "heard on its stream, not at a renewal"
        # The work it stopped reports a failure that is not kept: the item
        # runs again where it is claimed next.
        assert not await claimant.report(turn.item, ReportOutcome.failed, "stopped")
        assert claimant.journal.pending() == []


async def test_an_append_to_a_stream_its_kind_reads_wakes_the_work_within_a_second(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    transport: Counted,
    tmp_path: Path,
) -> None:
    claimant, pool_id = await a_claimant(client, owner, transport, tmp_path)
    product = build_kind_streams(container.infra, PRODUCT)
    org_id = (await tenant_of(container, owner)).org_id
    async with claimant.listening():
        await heard_open(claimant)
        await a_scan(container, owner, pool_id)
        turn = await claimant.turn()
        assert turn.item is not None
        item = turn.item
        for wait in (0.0, 1.5):
            # Once just after its claim, and once its stream read it as held.
            await asyncio.sleep(wait)
            woken = asyncio.ensure_future(claimant.appended(item, CUES, 30))
            await asyncio.sleep(0)
            sent = time.monotonic()
            await product.append(CUES, item.id, uuid4(), [(0, b"go")], org_id=org_id)
            assert await asyncio.wait_for(woken, timeout=5)
            assert time.monotonic() - sent < 1.0, time.monotonic() - sent
        # The fallback read: with nothing appended, the wait ends at its own.
        assert not await claimant.appended(item, CUES, 0.2)


async def stream_lines(claimant: Claimant, into: list[str], first: asyncio.Event) -> None:
    async with claimant.client() as api:
        async for line in api.claimant_control_stream():
            into.append(line.kind.value)
            first.set()


async def test_a_revoked_claimants_stream_ends_and_its_credential_opens_none(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    transport: Counted,
    tmp_path: Path,
) -> None:
    claimant, _ = await a_claimant(client, owner, transport, tmp_path)
    lines: list[str] = []
    first = asyncio.Event()
    stream = asyncio.ensure_future(stream_lines(claimant, lines, first))
    async with asyncio.timeout(5):
        await first.wait()
    assert lines[0] == ClaimantControlKind.wake.value

    claimant_id = claimant.enrollment.credential.claimant_id
    revoked = await client.delete(f"/v1/claimants/{claimant_id}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    async with asyncio.timeout(REREAD + 1):
        await stream
    # Its credential opens no stream again, and the kit stops listening
    # once refused, so its next turn raises.
    refused = await client.get(
        "/v1/claimants/me/control",
        headers={"Authorization": f"Bearer {claimant.enrollment.credential.token}"},
    )
    assert refused.status_code == 401, refused.text
    async with claimant.listening():
        async with asyncio.timeout(5):
            await claimant.woken.wait()
        assert claimant.enrollment.refused
        with pytest.raises(CredentialRefused):
            await claimant.turn()
    assert transport.calls.count("control") == 2


async def test_another_credential_opens_no_claimants_stream(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    for authorization in (owner["Authorization"], "Bearer scn_not-one", "Bearer hst_not-one"):
        answer = await client.get(
            "/v1/claimants/me/control", headers={"Authorization": authorization}
        )
        assert answer.status_code == 401, (authorization[:12], answer.text)
