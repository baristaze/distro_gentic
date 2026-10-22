"""A namespace a product declares in `product_api.py` and beside its kinds,
and nowhere else: the API serves its routes beside the platform's, under
the gateway's checks, and resolves its service by the namespace's name, with
no wiring file naming it; its service opens a live read and writes a stream
kind of the product's own through the live parts the API hands it, for its
caller's tenant alone, and writes only for a caller who may write; and one
served without being declared is refused at boot, since nothing would purge
its rows."""

import base64
import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

import pytest
from api_support import add_member, build_container, client_over, seed_request, sign_in, sign_in_as
from fastapi import APIRouter, Depends

from acme.om import product_namespaces
from acme.om.base import OmBase, new_id, utcnow
from acme.om.context import Permission, Role, TenantContext
from acme.om.placement.kinds import ClaimantKindSpec, PlacedKindSpec
from acme.om.platform_root import (
    PlatformManagers,
    PlatformPorts,
    ProductKinds,
    ProductNamespace,
    ProductNamespaces,
)
from acme.om.watch.kinds import StreamKind
from acme.om.watch.root import build_kind_streams
from acme.om.watch.types.live import ItemRead
from acme.om.work.types.work_item import WorkItem
from acme.services.api import product_api, routers
from acme.services.api.container import AppContainer
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.platform_resolve import product_service
from acme.services.api.products import ProductApi, ProductApiNamespace, ProductLive

from contracts import product_namespace
from contracts.product_namespace import NAMESPACE, NAMESPACES, PARCELS, Parcels

SHIP = "SHIP"
COURIER = "courier"
TRACKING = "parcel_tracking"
NOTES = "parcel_notes"
KEY = "k" * 32


class Shipment(OmBase):
    parcel: str


SHIPPING = ProductKinds(
    work=(
        PlacedKindSpec(
            SHIP, Shipment, Permission.WRITE, place=lambda _: "couriers", claimant=COURIER
        ),
    ),
    claimants=(ClaimantKindSpec(COURIER, lambda _: (("couriers", (SHIP,)),), prefix="cou_"),),
    streams=(
        # A shipment's tracking, which its courier writes, and its notes,
        # which the namespace's service writes and the courier reads.
        StreamKind(TRACKING, entries=4, bytes=4096, streams=2, claimant=COURIER),
        StreamKind(NOTES, entries=4, bytes=4096, streams=2, reader=COURIER),
    ),
)
"""What a product that ships parcels declares beside its namespaces."""


class ParcelsService:
    """The namespace's service: one call into its managers, or into the live
    parts, per route."""

    def __init__(self, parcels: Parcels, managers: PlatformManagers, live: ProductLive) -> None:
        self.parcels = parcels
        self.managers = managers
        self.live = live
        self.noted: dict[UUID, int] = {}

    async def note(self, ctx: TenantContext, item_id: UUID, text: str) -> None:
        """A note on a shipment, in the stream of notes its courier reads.
        The stream carries no tenant or permission of its own, so the
        caller holds WRITE, as the platform's write routes require, and the
        shipment is read under the caller's context first."""
        ctx.require(Permission.WRITE)
        item = await self.managers.work.get_item(ctx, item_id)
        number = self.noted.get(item.id, 0)
        await self.live.kind_streams.append(
            NOTES, item.id, item.id, ((number, text.encode()),), org_id=ctx.org_id
        )
        self.noted[item.id] = number + 1

    async def track(self, ctx: TenantContext, item_id: UUID) -> ItemRead:
        """A handle to the shipment's tracking, which its courier writes."""
        return await self.live.watch.open_item_live(ctx, item_id, TRACKING)


ParcelsServiceDep = Annotated[ParcelsService, Depends(product_service(PARCELS, ParcelsService))]

router = APIRouter(prefix="/parcels", tags=[PARCELS])


@router.post("", status_code=201)
async def add_parcel(ctx: Ctx, service: ParcelsServiceDep, name: str) -> list[str]:
    return await service.parcels.add(ctx, name)


@router.get("")
async def list_parcels(ctx: Ctx, service: ParcelsServiceDep) -> list[str]:
    return await service.parcels.list(ctx)


@router.post("/shipments/{item_id}/notes", status_code=204)
async def note_shipment(ctx: Ctx, service: ParcelsServiceDep, item_id: UUID, text: str) -> None:
    await service.note(ctx, item_id, text)


@router.post("/shipments/{item_id}/tracking/live")
async def track_shipment(ctx: Ctx, service: ParcelsServiceDep, item_id: UUID) -> ItemRead:
    return await service.track(ctx, item_id)


SERVED = ProductApi((ProductApiNamespace(NAMESPACE, (router,), ParcelsService),))
"""What a product that serves `parcels` declares in `product_api.py`."""


@pytest.fixture
def declared(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The product's two declarations hold `parcels`; the routers' registry
    is read again, as a process reads it at boot, and once more after."""
    monkeypatch.setattr(product_api, "PRODUCT_API", SERVED)
    monkeypatch.setattr(product_namespaces, "PRODUCT_NAMESPACES", NAMESPACES)
    importlib.reload(routers)
    yield
    monkeypatch.undo()
    importlib.reload(routers)


@pytest.mark.usefixtures("declared")
async def test_a_declared_namespaces_routes_are_served_and_its_service_resolves(
    tmp_path: Path,
) -> None:
    assert PARCELS in routers.HOSTED and router in routers.HOSTED[PARCELS]
    container = build_container(tmp_path)
    service = container.services.get_product_services()[PARCELS]
    assert isinstance(service, ParcelsService) and service.managers is container.managers
    assert service.parcels is product_namespace.built[-1], "built once, over the platform's"

    async with client_over(container) as client:
        assert (await client.get("/v1/parcels")).status_code == 401, "the gateway checks it"
        headers = await sign_in(client, container)
        added = await client.post("/v1/parcels", params={"name": "crate"}, headers=headers)
        assert added.status_code == 201, added.text
        listed = await client.get("/v1/parcels", headers=headers)

    assert listed.status_code == 200 and listed.json() == ["crate"]


async def a_shipment(container: AppContainer, ctx: TenantContext) -> WorkItem:
    now = utcnow()
    item = WorkItem(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        kind=SHIP,
        target_id=new_id(),
        idempotency_key=new_id(),
        request_id=new_id(),
        payload={"parcel": "crate"},
        available_at=now,
    )
    return await container.managers.work.enqueue(ctx, item)


@pytest.mark.usefixtures("declared")
async def test_a_declared_namespaces_service_opens_a_live_read_and_writes_its_own_kind(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path, ports=PlatformPorts(kinds=SHIPPING), live_read_key=KEY)
    # What the shipment's courier and the courier's reads stand in for.
    courier = build_kind_streams(container.infra, SHIPPING)

    async with client_over(container) as client:
        headers = await sign_in(client, container)
        ctx = await container.managers.tenancy.authenticate(
            seed_request(), headers["Authorization"].removeprefix("Bearer ")
        )
        beta, _ = await container.managers.tenancy.bootstrap(
            seed_request(), "Beta", "beta", "bea@beta.test", "Bea"
        )
        mine, theirs = await a_shipment(container, ctx), await a_shipment(container, beta)

        for text in ("fragile", "this side up"):
            noted = await client.post(
                f"/v1/parcels/shipments/{mine.id}/notes", params={"text": text}, headers=headers
            )
            assert noted.status_code == 204, noted.text
        await courier.append(
            TRACKING, mine.id, mine.id, [(0, b"picked up"), (1, b"in transit")], org_id=ctx.org_id
        )
        opened = await client.post(
            f"/v1/parcels/shipments/{mine.id}/tracking/live", headers=headers
        )
        assert opened.status_code == 200, opened.text
        assert (opened.json()["item_id"], opened.json()["kind"]) == (str(mine.id), TRACKING)
        page = await client.get("/v1/live/items", params={"handle": opened.json()["handle"]})
        assert page.status_code == 200, page.text
        (tracked,) = page.json()["streams"]
        assert [base64.b64decode(entry["data"]) for entry in tracked["entries"]] == [
            b"picked up",
            b"in transit",
        ]

        # A viewer of the tenant reads the shipment but writes no note.
        await add_member(container, ctx.org_id, "vic@example.test", Role.VIEWER)
        viewer = await sign_in_as(client, container, "vic@example.test", ctx.org_id)
        viewed = await client.post(
            f"/v1/parcels/shipments/{mine.id}/notes", params={"text": "x"}, headers=viewer
        )
        assert viewed.status_code == 403, viewed.text

        # Another tenant's shipment takes no note and opens no live read.
        refused = (
            await client.post(
                f"/v1/parcels/shipments/{theirs.id}/notes", params={"text": "x"}, headers=headers
            ),
            await client.post(f"/v1/parcels/shipments/{theirs.id}/tracking/live", headers=headers),
        )
        assert [answer.status_code for answer in refused] == [404, 404], [
            answer.text for answer in refused
        ]

    # The notes sit in the shipment's own group, where its courier reads
    # them, the viewer's is not among them, and nothing reached the other
    # tenant's.
    (notes,) = await courier.read(NOTES, mine.id, {})
    assert [entry for _, entry in notes.entries] == [b"fragile", b"this side up"]
    assert await courier.read(NOTES, theirs.id, {}) == ()


async def test_a_namespace_served_and_never_declared_is_refused_at_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_API", SERVED)
    monkeypatch.setattr(product_namespaces, "PRODUCT_NAMESPACES", ProductNamespaces())

    with pytest.raises(ValueError, match="parcels is served and not declared"):
        build_container(tmp_path)


def test_a_namespace_the_platform_hosts_is_refused_to_a_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taken = ProductNamespace("hosts", product_namespace.build_parcels)
    clash = ProductApi((ProductApiNamespace(taken, (router,), ParcelsService),))
    monkeypatch.setattr(product_api, "PRODUCT_API", clash)

    with pytest.raises(ValueError, match="namespace hosts is hosted twice"):
        importlib.reload(routers)
    monkeypatch.undo()
    importlib.reload(routers)
