"""A product's claimant streams the item it holds, end to end over the
compose stack: Postgres holds the item and its claim, and the shared cache
on Valkey holds the stream. A member of the item's tenant reads what the
claimant appended by a handle; a member of another tenant opens none, and
once the claimant hands the item back, nothing more lands. The highest
number an entry takes lands in Valkey, and a read resumes before it."""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from api_support import seed_request, sign_in_as
from tenant_support import tenant
from test_claimants_api import (
    KEY,
    LOG,
    PRODUCT,
    a_node,
    a_pool,
    a_token,
    append,
    bearer,
    entries,
    held_render,
    read,
)
from test_rate_limits_integration import an_address, settings_over_the_stack

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.om.base import new_id
from acme.om.root import PlatformPorts
from acme.om.watch.types.live import MAX_ENTRY
from acme.services.api.app import create_app
from acme.services.api.container import AppContainer, postgres_storage

pytestmark = pytest.mark.integration


async def test_a_claimants_stream_is_read_by_its_tenant_alone_over_the_stack(
    tmp_path: Path,
) -> None:
    settings = settings_over_the_stack(tmp_path, live_read_key=KEY)
    container = AppContainer.over(
        settings,
        postgres_storage(settings),
        InfraConfiguredImpl(settings),
        IntegrationsConfiguredImpl(settings, settings.environment, settings.is_cloud_environment),
        ports=PlatformPorts(kinds=PRODUCT),
    )
    await container.start()
    try:
        suffix = new_id().hex[-8:]
        email = f"ann-{suffix}@example.test"
        _, org = await container.managers.tenancy.bootstrap(
            seed_request(), "Ajax", f"ajax-{suffix}", email, "Ann"
        )
        transport = httpx.ASGITransport(
            app=create_app(container), client=(an_address(), 40000), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = await sign_in_as(client, email, org.id)
            pool_id = await a_pool(client, owner)
            node = await a_node(client, await a_token(client, owner, pool_id))
            render, claim_token = await held_render(client, container, owner, node)
            stream = uuid4()

            landed = await append(client, node, render.id, claim_token, stream, entries("f0", "f1"))
            assert landed.status_code == 204, landed.text
            assert await read(client, owner, render.id) == {str(stream): [(0, "f0"), (1, "f1")]}
            top = uuid4()
            highest = await append(
                client, node, render.id, claim_token, top, entries("top", start=MAX_ENTRY)
            )
            assert highest.status_code == 204, highest.text
            resumed = await read(client, owner, render.id, (f"{top}:{MAX_ENTRY - 1}",))
            assert resumed[str(top)] == [(MAX_ENTRY, "top")]

            beta = await tenant(client, container, f"beta-{suffix}")
            crossed = await client.post(
                f"/v1/work-items/{render.id}/streams/{LOG}/live", headers=beta.owner
            )
            assert crossed.status_code == 404, crossed.text

            reported = await client.post(
                f"/v1/claimants/me/items/{render.id}/report",
                headers=bearer(node["token"]),
                json={"claim_token": claim_token, "outcome": "done"},
            )
            assert reported.status_code == 200, reported.text
            late = await append(
                client, node, render.id, claim_token, stream, entries("f2", start=2)
            )
            assert late.status_code == 404, late.text
            assert await read(client, owner, render.id) == {
                str(stream): [(0, "f0"), (1, "f1")],
                str(top): [(MAX_ENTRY, "top")],
            }
    finally:
        await container.close()
