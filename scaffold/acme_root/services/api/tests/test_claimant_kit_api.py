"""A product's claimant built from the claimant kit, over the live app in
memory, with a product's kind registered in a test root: a `scan` job on
a `scanner` pool. The claimant names no credential call of its own: the
kit enrolls it once, keeps its credential owner-only, rotates it at half
its life, and stops it once the platform refuses it. It claims, renews,
and reports through `/claimants/...`, and a report the platform did not
answer waits in its journal and lands once."""

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import build_container, seed_request
from fastapi import FastAPI

from acme.client.claimant.claimant import Claimant
from acme.client.claimant.credential import load_credential
from acme.client.claimant.enrollment import CredentialRefused
from acme.client.claimant.settings import ClaimantSettings
from acme.client.client import ApiClient
from acme.client.types import ReportOutcome
from acme.om.base import Platform, new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.placement.kinds import ClaimantKindSpec
from acme.om.placement.types.claimant import Claimant as ClaimantRow
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.work.kinds import WorkKindSpec
from acme.om.work.types.work_item import WorkItem, WorkStatus
from acme.services.api.container import AppContainer

SCAN = "SCAN"
SCANNER = "scanner"


class ScanPayload(Platform):
    pool_id: UUID
    pages: int


def _scan_lane(payload: ScanPayload) -> str:
    return f"scanner:{payload.pool_id}"


def _scanner_claims(claimant: ClaimantRow) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return ((f"scanner:{claimant.pool_id}", (SCAN,)),)


PRODUCT = ProductKinds(
    work=(WorkKindSpec(SCAN, ScanPayload, Permission.WRITE, _scan_lane, claimant=SCANNER),),
    claimants=(ClaimantKindSpec(SCANNER, _scanner_claims, prefix="scn_"),),
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Outage(httpx.AsyncBaseTransport):
    """The app, or no answer at all while `down`; `lost` answers the next
    report with a timeout after the app recorded it. It counts the reports
    that reached the app."""

    inner: httpx.AsyncBaseTransport
    down: bool = False
    lost: bool = False
    reached: list[str] = field(default_factory=list)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("the platform is down", request=request)
        response = await self.inner.handle_async_request(request)
        if request.url.path.endswith("/report"):
            self.reached.append(request.url.path)
            if self.lost:
                self.lost = False
                await response.aread()
                raise httpx.ReadTimeout("the answer was lost", request=request)
        return response


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test root, with the product's kinds registered; the `app`,
    `client`, and `owner` fixtures run over it."""
    return build_container(tmp_path, ports=PlatformPorts(kinds=PRODUCT))


@pytest.fixture
def outage(app: FastAPI) -> Outage:
    return Outage(httpx.ASGITransport(app=app, raise_app_exceptions=False))


def client_for(transport: httpx.AsyncBaseTransport) -> Callable[[str | None], ApiClient]:
    def build(token: str | None) -> ApiClient:
        return ApiClient(
            "http://test", app="api", app_version="scanner@test", token=token, transport=transport
        )

    return build


def settings(home: Path, token: str | None) -> ClaimantSettings:
    return ClaimantSettings(
        api_url="http://test", home=home, name="scanner-1", enrollment_token=token
    )


async def a_pool_token(client: httpx.AsyncClient, owner: dict[str, str]) -> tuple[str, str]:
    created = await client.post(
        "/v1/host-pools",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"name": "scanners", "region": "eu-west"},
    )
    assert created.status_code == 201, created.text
    pool_id = created.json()["id"]
    issued = await client.post(
        f"/v1/host-pools/{pool_id}/enrollment-tokens", headers=owner, json={"kind": SCANNER}
    )
    assert issued.status_code == 200, issued.text
    return pool_id, issued.json()["token"]


async def tenant_of(container: AppContainer, owner: dict[str, str]) -> TenantContext:
    token = owner["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def a_scan(container: AppContainer, owner: dict[str, str], pool_id: str) -> WorkItem:
    ctx = await tenant_of(container, owner)
    now = utcnow()
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=SCAN,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload={"pool_id": pool_id, "pages": 3},
        available_at=now,
    )
    return await container.managers.work.enqueue(ctx, item)


async def status_of(container: AppContainer, owner: dict[str, str], item_id: UUID) -> WorkStatus:
    ctx = await tenant_of(container, owner)
    return (await container.managers.work.get_item(ctx, item_id)).status


async def test_a_claimant_built_from_the_kit_enrolls_claims_renews_and_reports(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    outage: Outage,
    tmp_path: Path,
) -> None:
    pool_id, token = await a_pool_token(client, owner)
    claimant = Claimant(settings(tmp_path, token), client_for(outage))
    await claimant.start()
    held = claimant.enrollment.credential
    assert held.token.startswith("scn_") and held.pool_id == pool_id

    scan = await a_scan(container, owner, pool_id)
    turn = await claimant.turn()
    assert turn.item is not None and turn.wait == 0.0
    assert (turn.item.id, turn.item.kind, turn.item.payload["pages"]) == (scan.id, SCAN, 3)
    renewed = await claimant.renew(turn.item)
    assert renewed.lease_expires_at is not None and turn.item.lease_expires_at is not None
    assert renewed.lease_expires_at >= turn.item.lease_expires_at
    assert await claimant.report(turn.item, ReportOutcome.done)
    assert await status_of(container, owner, scan.id) is WorkStatus.DONE
    assert claimant.journal.pending() == [] and outage.reached == [
        f"/v1/claimants/me/items/{scan.id}/report"
    ]
    idle = await claimant.turn()
    assert idle.item is None and idle.wait == settings(tmp_path, None).beat_seconds

    # Started again with no token, it picks up the credential it holds.
    again = Claimant(settings(tmp_path, None), client_for(outage))
    await again.start()
    assert again.enrollment.credential == held


async def test_its_credential_is_kept_owner_only_rotated_at_half_its_life_and_never_sent_once_refused(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    outage: Outage,
    tmp_path: Path,
) -> None:
    pool_id, token = await a_pool_token(client, owner)
    clock = Clock()
    claimant = Claimant(settings(tmp_path, token), client_for(outage), now=clock)
    await claimant.start()
    first = claimant.enrollment.credential
    path = tmp_path / "credential.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert token not in path.read_text()
    assert [name for name in os.listdir(tmp_path) if name.startswith(".")] == []

    # Not before half its life; at half, once, and kept before it is used.
    await claimant.turn()
    assert claimant.enrollment.credential == first
    clock.now += (first.expires_at - first.issued_at) / 2 + timedelta(seconds=1)
    await claimant.turn()
    rotated = claimant.enrollment.credential
    assert rotated.token != first.token and rotated.claimant_id == first.claimant_id
    assert load_credential(path) == rotated
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    await claimant.turn()
    assert claimant.enrollment.credential == rotated

    # Revoked by its owner: the next turn is refused, and no call after it
    # carries the credential.
    revoked = await client.delete(f"/v1/claimants/{first.claimant_id}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(CredentialRefused):
        await claimant.turn()
    outage.down = True  # any call that went out now would fail as the wire, not as refused
    with pytest.raises(CredentialRefused):
        await claimant.turn()
    with pytest.raises(CredentialRefused):
        claimant.client()
    await a_scan(container, owner, pool_id)
    with pytest.raises(CredentialRefused):
        await claimant.turn(claim=True)


async def test_a_report_the_platform_did_not_answer_waits_in_the_journal_and_lands_once(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    outage: Outage,
    tmp_path: Path,
) -> None:
    pool_id, token = await a_pool_token(client, owner)
    claimant = Claimant(settings(tmp_path, token), client_for(outage), jitter=lambda: 0.0)
    await claimant.start()
    first, second = await a_scan(container, owner, pool_id), await a_scan(container, owner, pool_id)
    held = (await claimant.turn()).item
    assert held is not None and held.id == first.id

    # The platform is down: the report is kept on the disk, owner-only.
    outage.down = True
    assert not await claimant.report(held, ReportOutcome.done)
    kept = claimant.journal.pending()
    assert [(e.key, e.body["outcome"]) for e in kept] == [(str(first.id), "done")]
    entry = tmp_path / "journal" / f"{first.id}.json"
    assert stat.S_IMODE(entry.stat().st_mode) == 0o600
    # While it waits, the claimant claims nothing, and waits longer each time.
    waits = [(await claimant.turn()).wait for _ in range(3)]
    assert waits == sorted(waits) and waits[0] > 0
    assert claimant.journal.pending() == kept and outage.reached == []

    # Back: the next turn sends it once, then claims the next item.
    outage.down = False
    turn = await claimant.turn()
    assert outage.reached == [f"/v1/claimants/me/items/{first.id}/report"]
    assert await status_of(container, owner, first.id) is WorkStatus.DONE
    assert claimant.journal.pending() == []
    assert turn.item is not None and turn.item.id == second.id

    # The platform records a report whose answer is lost: sent again, it is
    # refused as no longer this claim's, and never sent a third time.
    outage.lost = True
    assert not await claimant.report(turn.item, ReportOutcome.done)
    assert await status_of(container, owner, second.id) is WorkStatus.DONE
    await claimant.turn()
    await claimant.turn()
    assert outage.reached.count(f"/v1/claimants/me/items/{second.id}/report") == 2
    assert claimant.journal.pending() == []
    assert await status_of(container, owner, second.id) is WorkStatus.DONE
