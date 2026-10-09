"""A product's own resource kind, registered through `ProductKinds` at the
platform's root, beside `noop`: asked for, granted, and revoked through the
leases' routes, with its hooks asked at each grant and its ask held to its
shape; a kind no one registered refused; and the kind's check refusing an
ask before it waits. The example is a `dock` a product registers."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from api_support import add_member, build_container, client_over, seed_request, sign_in, sign_in_as
from pydantic import Field

from acme.om.base import EMPTY_UUID, Platform, new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.exceptions import NotAuthorized
from acme.om.leases.hooks import AskCheckInterface, ResourceKindInterface
from acme.om.leases.kinds import ResourceKindSpec
from acme.om.leases.types.lease import Lease
from acme.om.leases.types.request import LeaseRequest
from acme.om.leases.types.resource import Resource
from acme.om.outbox.types.row import OutboxRow
from acme.om.root import Managers, PlatformPorts, ProductKinds
from acme.services.api.container import AppContainer

DOCK = "dock"


class DockAsk(Platform):
    """What an ask for a dock carries: the bay it backs into."""

    bay: int = Field(ge=1)


class DockHooks(ResourceKindInterface):
    """The product's hooks, built over the managers as its tools are. They
    keep what each grant asked of them."""

    def __init__(self, managers: Callable[[], Managers]) -> None:
        self.managers = managers
        self.asked: list[UUID] = []
        self.started: list[tuple[UUID, int]] = []

    async def may_grant(
        self, ctx: TenantContext, resource: Resource, request: LeaseRequest
    ) -> bool:
        self.asked.append(request.id)
        return True

    def grant_rows(
        self, ctx: TenantContext, resource: Resource, request: LeaseRequest, lease: Lease
    ) -> tuple[OutboxRow, ...]:
        self.started.append((request.id, lease.token))
        return ()


class OwnersAlone(AskCheckInterface):
    """The product's check: only the owner asks for a dock."""

    async def check_ask(
        self, ctx: TenantContext, request: LeaseRequest, resource: Resource | None
    ) -> None:
        if ctx.role is not Role.OWNER:
            raise NotAuthorized(f"a {ctx.role.value} asks for no {request.kind}")


class Product:
    """A product that registers the dock, with the check or without it, and
    keeps the hooks the root built over its managers."""

    def __init__(self, check: AskCheckInterface | None = None) -> None:
        self.check = check
        self.hooks: DockHooks | None = None

    def resources(self, managers: Callable[[], Managers]) -> tuple[ResourceKindSpec, ...]:
        self.hooks = DockHooks(managers)
        return (ResourceKindSpec(DOCK, DockAsk, self.hooks, self.check),)

    def container(self, tmp_path: Path) -> AppContainer:
        return build_container(
            tmp_path, ports=PlatformPorts(kinds=ProductKinds(resources=self.resources))
        )


async def org_of(client: httpx.AsyncClient, headers: dict[str, str]) -> UUID:
    return UUID((await client.get("/v1/me", headers=headers)).json()["org"]["id"])


async def a_dock(container: AppContainer, org_id: UUID) -> Resource:
    """A dock its owner namespace registers, as no route does."""
    ctx = await container.managers.tenancy.service_context(seed_request(), org_id, EMPTY_UUID)
    now = utcnow()
    return await container.managers.leases.register(
        ctx,
        Resource(
            id=new_id(), created_at=now, updated_at=now, created_by=EMPTY_UUID,
            updated_by=EMPTY_UUID, kind=DOCK, ref_id=new_id(),
        ),
    )  # fmt: skip


async def ask(client: httpx.AsyncClient, headers: dict[str, str], **body: Any) -> httpx.Response:
    return await client.post(
        "/v1/leases/requests", headers={**headers, "Idempotency-Key": str(uuid4())}, json=body
    )


async def a_member(
    client: httpx.AsyncClient, container: AppContainer, org_id: UUID, name: str
) -> dict[str, str]:
    await add_member(container, org_id, f"{name}@example.test", Role.MEMBER)
    return await sign_in_as(client, f"{name}@example.test", org_id)


async def test_a_products_kind_is_asked_for_granted_and_revoked_through_the_routes(
    tmp_path: Path,
) -> None:
    product = Product()
    container = product.container(tmp_path)
    hooks = product.hooks
    assert hooks is not None and hooks.managers() is container.managers
    async with client_over(container) as client:
        owner = await sign_in(client, container)
        org_id = await org_of(client, owner)
        dock = await a_dock(container, org_id)
        kai = await a_member(client, container, org_id, "kai")
        mia = await a_member(client, container, org_id, "mia")

        first = await ask(client, kai, kind=DOCK, resource_id=str(dock.id), payload={"bay": 3})
        assert first.status_code == 201, first.text
        held = first.json()
        assert held["request"]["kind"] == DOCK and held["lease"]["fencing_token"] == 1
        assert hooks.asked == [UUID(held["request"]["id"])]
        assert hooks.started == [(UUID(held["request"]["id"]), 1)]

        second = await ask(client, mia, kind=DOCK, resource_id=str(dock.id), payload={"bay": 4})
        waits = second.json()
        assert second.status_code == 201 and waits["lease"] is None and waits["place"] == 1
        line = await client.get(f"/v1/leases/resources/{dock.id}/line", headers=kai)
        assert line.json()["resource"]["kind"] == DOCK

        revoked = await client.post(f"/v1/leases/{held['lease']['id']}/revoke", headers=owner)
        assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
        now = (
            await client.get(f"/v1/leases/requests/{waits['request']['id']}", headers=mia)
        ).json()
        assert now["request"]["status"] == "granted" and now["lease"]["fencing_token"] == 2
        assert hooks.started[-1] == (UUID(waits["request"]["id"]), 2)

        off_shape = await ask(client, kai, kind=DOCK, resource_id=str(dock.id), payload={"bay": 0})
        assert off_shape.status_code == 422, off_shape.text
        unknown = await ask(client, kai, kind="crane", labels=[])
        assert unknown.status_code == 422, unknown.text
        assert "no resource kind crane" in unknown.json()["error"]["message"]
        assert len(hooks.started) == 2, "neither refusal reached the kind's hooks"


async def test_a_products_check_refuses_an_ask_before_it_waits(tmp_path: Path) -> None:
    product = Product(OwnersAlone())
    container = product.container(tmp_path)
    hooks = product.hooks
    assert hooks is not None
    async with client_over(container) as client:
        owner = await sign_in(client, container)
        org_id = await org_of(client, owner)
        dock = await a_dock(container, org_id)
        mia = await a_member(client, container, org_id, "mia")

        refused = await ask(client, mia, kind=DOCK, resource_id=str(dock.id), payload={"bay": 2})
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "not_authorized"
        line = await client.get(f"/v1/leases/resources/{dock.id}/line", headers=owner)
        assert line.json()["requests"] == [] and line.json()["resource"]["lease_id"] is None
        assert hooks.asked == [], "the refused ask never reached a grant"

        held = await ask(client, owner, kind=DOCK, resource_id=str(dock.id), payload={"bay": 2})
        assert held.status_code == 201 and held.json()["lease"]["fencing_token"] == 1
        noop = await ask(client, mia, kind="noop", labels=[])
        assert noop.status_code == 201, "the check is the dock's alone"
