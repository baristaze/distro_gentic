"""What the tests of a tenant's configuration share: two tenants over one
app, each with its owner signed in, and a person of any role signed in to
the first. Every route is held to its tenant: another tenant's id is
answered as one that never existed is."""

from dataclasses import dataclass
from uuid import UUID

import httpx
from api_support import add_member, seed_request, sign_in_as

from acme.om.context import Role
from acme.services.api.container import AppContainer

Headers = dict[str, str]


@dataclass(frozen=True)
class Tenant:
    org_id: UUID
    owner: Headers


async def tenant(client: httpx.AsyncClient, container: AppContainer, slug: str) -> Tenant:
    """A tenant bootstrapped with its owner, signed in."""
    email = f"owner@{slug}.test"
    _, org = await container.managers.tenancy.bootstrap(
        seed_request(), slug.title(), slug, email, slug.title()
    )
    return Tenant(org.id, await sign_in_as(client, email, org.id))


async def person(
    client: httpx.AsyncClient, container: AppContainer, org_id: UUID, role: Role
) -> Headers:
    """A person of the role in the tenant, signed in."""
    email = f"{role.value}-{org_id.hex[:8]}@example.test"
    await add_member(container, org_id, email, role)
    return await sign_in_as(client, email, org_id)


def refused(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text
