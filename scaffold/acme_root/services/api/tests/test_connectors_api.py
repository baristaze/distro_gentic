"""A tenant's connectors over the live app, in memory: a person who manages
the tenant connects a server, reads what it lists, reviews its tools in
person, and attaches it to a kind; the credential comes back in no
response; a member connects nothing; a cloud address the platform's cloud
must not call is refused; a host's server is listed on its host; and a
malformed connector or review is refused with its reason."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import add_member, build_container, client_over, sign_in, sign_in_as
from unit.test_connectors import OPERATOR, RECORDS, Served, serve

from acme.integrations.mcp import McpListedTool
from acme.om.connectors.impl.manager import connector_secret
from acme.om.context import Role
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.tools.mcp import definition_of
from acme.om.tools.rules import definition_hash
from acme.services.api.container import AppContainer
from acme.services.api.types.connectors import ReviewedToolBody

TOKEN = "tok-0d6a92ce51b7f3"
PORTS = PlatformPorts(kinds=ProductKinds(agents=(OPERATOR,), toolsets=(RECORDS,)))


@pytest.fixture
def words() -> Iterator[Served]:
    served = serve()
    try:
        yield served
    finally:
        served.stop()


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """A local stack's app, whose servers run beside it, with the operator
    kind a connector attaches to."""
    return build_container(tmp_path, ports=PORTS, environment="local")


async def test_a_server_is_connected_reviewed_and_attached_and_its_credential_never_answered(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str], words: Served
) -> None:
    connected = await client.post(
        "/v1/connectors",
        headers={**owner, "Idempotency-Key": "connect-words"},
        json={"name": "words", "summary": "Look words up.", "url": words.url},
    )
    assert connected.status_code == 201, connected.text
    connector = connected.json()
    assert not connector["has_credential"] and connector["tools"] == [] and connector["review"] == 0
    given = await client.put(
        f"/v1/connectors/{connector['id']}/credential", headers=owner, json={"value": TOKEN}
    )
    assert given.status_code == 200, given.text
    assert given.json()["has_credential"] and TOKEN not in given.text
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    stored = await container.infra.get_secrets().get(
        UUID(org_id), connector_secret(UUID(connector["id"]))
    )
    assert stored == TOKEN, "the value is in the tenant's store, and nowhere the API answers"

    listing = await client.get(f"/v1/connectors/{connector['id']}/listing", headers=owner)
    assert listing.status_code == 200, listing.text
    listed = {tool["name"]: tool for tool in listing.json()}
    assert listed["lookup"]["description"] == "Looks a word up."
    assert listed["lookup"]["definition_hash"].startswith("sha256:")

    reviewed = await client.post(
        f"/v1/connectors/{connector['id']}/review",
        headers=owner,
        json={
            "tools": [
                {
                    "server_tool": "lookup",
                    "definition_hash": listed["lookup"]["definition_hash"],
                    "authorization_class": "read",
                    "effect": "read_only",
                }
            ]
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    (tool,) = reviewed.json()["tools"]
    assert (tool["name"], tool["server_tool"], tool["authorization_class"]) == (
        "words__lookup",
        "lookup",
        "read",
    )
    assert reviewed.json()["review"] == 1

    stale = await client.post(
        f"/v1/connectors/{connector['id']}/review",
        headers=owner,
        json={
            "tools": [
                {
                    "server_tool": "lookup",
                    "definition_hash": "sha256:read-before",
                    "authorization_class": "read",
                    "effect": "read_only",
                }
            ]
        },
    )
    assert stale.status_code == 422, "a definition the person did not read binds nothing"

    attached = await client.post(
        f"/v1/connectors/{connector['id']}/attachments",
        headers=owner,
        json={"kind": "operator"},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["attachments"] == [
        {"kind": "operator", "project_id": None, "deferred": True}
    ]
    detached = await client.delete(
        f"/v1/connectors/{connector['id']}/attachments",
        headers=owner,
        params={"kind": "operator"},
    )
    assert detached.status_code == 200 and detached.json()["attachments"] == []
    again = await client.delete(
        f"/v1/connectors/{connector['id']}/attachments",
        headers=owner,
        params={"kind": "operator"},
    )
    assert again.status_code == 404
    everything = await client.get("/v1/connectors", headers=owner)
    assert [each["name"] for each in everything.json()] == ["words"]
    assert TOKEN not in everything.text


async def test_a_member_connects_nothing_and_a_host_server_is_listed_on_its_host(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    await add_member(container, UUID(org_id), "mia@example.test", Role.MEMBER)
    member = await sign_in_as(client, "mia@example.test", UUID(org_id))
    body = {"name": "tracker", "summary": "Read the team's tickets.", "host_server": "tracker"}
    refused = await client.post("/v1/connectors", headers=member, json=body)
    assert refused.status_code == 403, refused.text
    inside = await client.post("/v1/connectors", headers=owner, json=body)
    assert inside.status_code == 201, inside.text
    assert inside.json()["place"] == "host" and not inside.json()["has_credential"]
    listing = await client.get(f"/v1/connectors/{inside.json()['id']}/listing", headers=owner)
    assert listing.status_code == 409, "the platform never reaches into the wall"
    held = await client.put(
        f"/v1/connectors/{inside.json()['id']}/credential", headers=owner, json={"value": TOKEN}
    )
    assert held.status_code == 422, "its credential stays on its host"
    assert TOKEN not in held.text


@pytest.fixture
async def deployed(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    """An app outside a local stack, which calls the public internet alone."""
    container = build_container(tmp_path, ports=PORTS)
    async with client_over(container) as client:
        yield client, await sign_in(client, container)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8392/mcp",
        "https://127.0.0.1/mcp",
        "https://169.254.169.254/latest",
        "https://10.0.0.7/mcp",
        "https://localhost/mcp",
    ],
)
async def test_an_address_the_cloud_must_not_call_is_refused(
    deployed: tuple[httpx.AsyncClient, dict[str, str]], url: str
) -> None:
    client, owner = deployed
    refused = await client.post(
        "/v1/connectors",
        headers=owner,
        json={"name": "words", "summary": "Look words up.", "url": url},
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            {
                "name": "words",
                "summary": "Look.",
                "url": "http://127.0.0.1:9/mcp",
                "host_server": "w",
            },
            "has an address, or names its host's server",
        ),
        ({"name": "words", "summary": "Look."}, "has an address, or names its host's server"),
        (
            {"name": "words", "summary": "one\ntwo", "host_server": "words"},
            "summary is one line",
        ),
    ],
    ids=["both-places", "no-place", "two-line-summary"],
)
async def test_a_malformed_connector_is_refused_with_its_reason(
    client: httpx.AsyncClient, owner: dict[str, str], body: dict[str, str], reason: str
) -> None:
    refused = await client.post("/v1/connectors", headers=owner, json=body)
    assert refused.status_code == 422, refused.text
    assert reason in refused.text


async def test_a_review_offers_and_takes_a_server_tools_classes_alone(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    inside = await client.post(
        "/v1/connectors",
        headers=owner,
        json={"name": "tracker", "summary": "Read tickets.", "host_server": "tracker"},
    )
    assert inside.status_code == 201, inside.text
    definition = definition_of(McpListedTool(name="find", description="Finds a ticket."))
    tool = {
        "server_tool": "find",
        "definition_hash": definition_hash(definition),
        "effect": "read_only",
    }
    refused = await client.post(
        f"/v1/connectors/{inside.json()['id']}/review",
        headers=owner,
        json={
            "tools": [{**tool, "authorization_class": "execute"}],
            "definitions": [definition.model_dump(mode="json")],
        },
    )
    assert refused.status_code == 422, refused.text
    assert "authorization_class" in refused.text
    offered = ReviewedToolBody.model_json_schema()["properties"]["authorization_class"]["enum"]
    assert sorted(offered) == ["destructive", "integration", "read"]
