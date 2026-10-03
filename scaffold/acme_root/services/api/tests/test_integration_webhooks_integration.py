"""An integration's deliveries over the compose stack's Postgres: the
ingress reads the tenant that connected the installation a delivery names
across every tenant's rows, and queues the delivery under that tenant
alone. A delivery naming an installation no tenant connected, or a
tenant's org id, queues nothing, and no tenant takes over another's
installation."""

import random
from pathlib import Path
from uuid import UUID

import pytest
from api_support import seed_request, sign_in_as
from test_hosts_api import tenant_of
from test_integration_webhooks_api import CONNECT, ROUTE, a_check, connect, queued
from test_rate_limits_integration import over_the_stack

from acme.infra.queues import Queues
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.om.base import new_id, utcnow

pytestmark = pytest.mark.integration


def an_installation() -> str:
    """A forge's id for an installation no other run of the shared database
    holds: one installation is one tenant's across every tenant."""
    return str(random.randrange(10**11, 10**12))


async def test_a_delivery_reaches_the_tenant_that_connected_its_installation_over_the_stack(
    tmp_path: Path,
) -> None:
    async with over_the_stack(tmp_path, integrations="twin") as (container, client, ajax):
        forge = container.integrations.get_integration("forge")
        assert isinstance(forge, IntegrationTwinImpl)
        ajax_id = (await tenant_of(container, ajax)).org_id
        suffix = new_id().hex[-8:]
        email = f"bo-{suffix}@example.test"
        _, org = await container.managers.tenancy.bootstrap(
            seed_request(), "Bravo", f"bravo-{suffix}", email, "Bo"
        )
        bravo = await sign_in_as(client, email, org.id)
        mine, theirs = an_installation(), an_installation()
        for headers, installation in ((ajax, mine), (bravo, theirs)):
            connected = await connect(client, headers, forge, installation)
            assert connected.status_code == 201, connected.text
        taken = await client.post(
            CONNECT, headers=bravo, json={"grant": forge.grant(mine, utcnow())}
        )
        assert taken.status_code == 409, taken.text

        for installation in (mine, theirs):
            payload, signed = a_check(forge, installation)
            answered = await client.post(ROUTE, content=payload, headers=signed)
            assert answered.status_code == 200, answered.text
        to_ajax, to_bravo = await queued(container)
        reached = [UUID(sent["delivery"]["org_id"]) for sent in (to_ajax, to_bravo)]  # type: ignore[index]
        assert reached == [ajax_id, org.id]

        for named in (an_installation(), str(ajax_id)):
            payload, signed = a_check(forge, named)
            refused = await client.post(ROUTE, content=payload, headers=signed)
            assert refused.status_code == 400, refused.text
        depth = await container.infra.get_queues().depth(Queues.WEBHOOKS)
        assert (depth.visible, depth.in_flight) == (0, 0)
