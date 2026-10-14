"""A namespace a product declares in `product_api.py` and beside its kinds,
and nowhere else: the API serves its routes beside the platform's, under
the gateway's checks, and resolves its service by the namespace's name, with
no wiring file naming it; and one served without being declared is refused
at boot, since nothing would purge its rows."""

import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from api_support import build_container, client_over, sign_in
from contracts import product_namespace
from contracts.product_namespace import NAMESPACE, NAMESPACES, PARCELS, Parcels
from fastapi import APIRouter, Depends

from acme.om import product_namespaces
from acme.om.platform_root import PlatformManagers, ProductNamespace, ProductNamespaces
from acme.services.api import product_api, routers
from acme.services.api.gateway.auth import Ctx
from acme.services.api.gateway.platform_resolve import product_service
from acme.services.api.products import ProductApi, ProductApiNamespace


class ParcelsService:
    """The namespace's service: one call into its managers per route."""

    def __init__(self, parcels: Parcels, managers: PlatformManagers) -> None:
        self.parcels = parcels
        self.managers = managers


ParcelsServiceDep = Annotated[ParcelsService, Depends(product_service(PARCELS, ParcelsService))]

router = APIRouter(prefix="/parcels", tags=[PARCELS])


@router.post("", status_code=201)
async def add_parcel(ctx: Ctx, service: ParcelsServiceDep, name: str) -> list[str]:
    return await service.parcels.add(ctx, name)


@router.get("")
async def list_parcels(ctx: Ctx, service: ParcelsServiceDep) -> list[str]:
    return await service.parcels.list(ctx)


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
    service = container.services.get_product_service(PARCELS)
    assert isinstance(service, ParcelsService) and service.managers is container.managers
    assert service.parcels is product_namespace.built[-1], "built once, over the platform's"

    async with client_over(container) as client:
        assert (await client.get("/v1/parcels")).status_code == 401, "the gateway checks it"
        headers = await sign_in(client, container)
        added = await client.post("/v1/parcels", params={"name": "crate"}, headers=headers)
        assert added.status_code == 201, added.text
        listed = await client.get("/v1/parcels", headers=headers)

    assert listed.status_code == 200 and listed.json() == ["crate"]


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
