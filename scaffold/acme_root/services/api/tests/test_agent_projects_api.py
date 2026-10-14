"""A tenant's agent projects over the API: an owner creates one bound to its
repository, reads, lists, renames, and removes it, and gives its repository
a fetch credential, which is written to the tenant's store and never read
back. A member reads the agent projects and writes none of them; another
tenant's agent project is not found; a malformed body is refused whole."""

from uuid import UUID

import httpx
from tenant_support import person, refused, tenant

from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.agent_workspaces.rules import fetch_secret_name
from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.services.api.container import AppContainer

AGENT_PROJECT = {
    "name": "the weekly reports",
    "repository": {"host": "GitHub.com", "path": "Octo/Reports"},
}
PASSWORD = "ghp_never-read-back-0123456789"
CREDENTIAL = {"username": "reader", "password": PASSWORD}


async def created(client: httpx.AsyncClient, headers: dict[str, str]) -> UUID:
    response = await client.post("/v1/agent-projects", headers=headers, json=AGENT_PROJECT)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def test_an_owner_creates_reads_lists_renames_and_removes_an_agent_project(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    made = await client.post("/v1/agent-projects", headers=ajax.owner, json=AGENT_PROJECT)
    assert made.status_code == 201, made.text
    agent_project = made.json()
    assert agent_project["repository"] == {"host": "github.com", "path": "octo/reports"}
    url = f"/v1/agent-projects/{agent_project['id']}"
    got = await client.get(url, headers=ajax.owner)
    assert got.status_code == 200, got.text
    assert got.json() == agent_project
    listed = await client.get("/v1/agent-projects", headers=ajax.owner)
    assert [p["id"] for p in listed.json()] == [agent_project["id"]]
    after = await client.get(
        "/v1/agent-projects", headers=ajax.owner, params={"after": agent_project["id"]}
    )
    assert after.json() == []
    renamed = await client.patch(url, headers=ajax.owner, json={"name": "the monthly reports"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "the monthly reports"
    assert renamed.json()["repository"] == agent_project["repository"]
    removed = await client.delete(url, headers=ajax.owner)
    assert removed.status_code == 200, removed.text
    assert removed.json()["name"] == "the monthly reports"
    refused(await client.get(url, headers=ajax.owner), 404, "not_found")


async def test_a_fetch_credential_is_written_to_the_store_and_never_read_back(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    agent_project_id = await created(client, ajax.owner)
    url = f"/v1/agent-projects/{agent_project_id}/credential"
    first = await client.put(url, headers=ajax.owner, json=CREDENTIAL)
    assert first.status_code == 200, first.text
    assert first.json()["agent_project_id"] == str(agent_project_id)
    assert first.json()["version"] == 1
    again = await client.put(url, headers=ajax.owner, json=CREDENTIAL)
    assert again.json()["version"] == 2
    reads = [
        first,
        again,
        await client.get(f"/v1/agent-projects/{agent_project_id}", headers=ajax.owner),
        await client.get("/v1/agent-projects", headers=ajax.owner),
    ]
    assert all(PASSWORD not in r.text and "password" not in r.text for r in reads)
    secrets, name = container.infra.get_secrets(), fetch_secret_name(agent_project_id)
    assert PASSWORD in await secrets.get(ajax.org_id, name)
    # Removed with its agent project, the credential leaves the store and its record goes.
    removed = await client.delete(f"/v1/agent-projects/{agent_project_id}", headers=ajax.owner)
    assert removed.status_code == 200, removed.text
    assert PASSWORD not in removed.text
    assert not await secrets.has(ajax.org_id, name)
    workspaces = container.storage.get_agent_workspace_storage()
    assert await workspaces.read_credential(ajax.org_id, agent_project_id) is None


async def test_an_agent_project_a_session_belongs_to_stays_with_its_credential(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    agent_project_id = await created(client, ajax.owner)
    url = f"/v1/agent-projects/{agent_project_id}"
    await client.put(f"{url}/credential", headers=ajax.owner, json=CREDENTIAL)
    binding = SessionAgentProject(
        id=new_id(), created_at=utcnow(), agent_project_id=agent_project_id
    )
    await container.storage.get_agent_project_storage().bind_session(ajax.org_id, binding)
    refused(await client.delete(url, headers=ajax.owner), 409, "agent_project_in_use")
    assert (await client.get(url, headers=ajax.owner)).status_code == 200
    secrets = container.infra.get_secrets()
    assert await secrets.has(ajax.org_id, fetch_secret_name(agent_project_id))


async def test_a_member_reads_agent_projects_and_writes_none(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    agent_project_id = await created(client, ajax.owner)
    url = f"/v1/agent-projects/{agent_project_id}"
    for role in (Role.MEMBER, Role.VIEWER):
        headers = await person(client, container, ajax.org_id, role)
        assert (await client.get(url, headers=headers)).status_code == 200
        assert (await client.get("/v1/agent-projects", headers=headers)).status_code == 200
        writes = [
            await client.post("/v1/agent-projects", headers=headers, json=AGENT_PROJECT),
            await client.patch(url, headers=headers, json={"name": "taken"}),
            await client.delete(url, headers=headers),
            await client.put(f"{url}/credential", headers=headers, json=CREDENTIAL),
        ]
        for response in writes:
            refused(response, 403, "not_authorized")
    assert (await client.get(url, headers=ajax.owner)).json()["name"] == AGENT_PROJECT["name"]
    workspaces = container.storage.get_agent_workspace_storage()
    assert await workspaces.read_credential(ajax.org_id, agent_project_id) is None


async def test_another_tenants_agent_project_is_not_found_and_left_as_it_is(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bravo = await tenant(client, container, "bravo")
    agent_project_id = await created(client, ajax.owner)
    url = f"/v1/agent-projects/{agent_project_id}"
    crossings = [
        await client.get(url, headers=bravo.owner),
        await client.patch(url, headers=bravo.owner, json={"name": "taken"}),
        await client.delete(url, headers=bravo.owner),
        await client.put(f"{url}/credential", headers=bravo.owner, json=CREDENTIAL),
    ]
    for response in crossings:
        refused(response, 404, "not_found")
    assert (await client.get("/v1/agent-projects", headers=bravo.owner)).json() == []
    assert (await client.get(url, headers=ajax.owner)).json()["name"] == AGENT_PROJECT["name"]
    secrets = container.infra.get_secrets()
    assert not await secrets.has(bravo.org_id, fetch_secret_name(agent_project_id))
    assert not await secrets.has(ajax.org_id, fetch_secret_name(agent_project_id))


async def test_a_malformed_agent_project_or_credential_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    agent_project_id = await created(client, ajax.owner)
    bad_agent_projects = [
        {**AGENT_PROJECT, "name": ""},
        {**AGENT_PROJECT, "repository": {"host": "github.com", "path": "../etc"}},
        {**AGENT_PROJECT, "repository": {"host": "not a host", "path": "octo/reports"}},
        {**AGENT_PROJECT, "extra": True},
        {"name": "no repository"},
    ]
    for body in bad_agent_projects:
        refused(
            await client.post("/v1/agent-projects", headers=ajax.owner, json=body),
            422,
            "validation_failed",
        )
    url = f"/v1/agent-projects/{agent_project_id}/credential"
    secret_bodies = [
        {"username": "has:colon", "password": PASSWORD},
        {"username": "reader", "password": ""},
        {"username": "reader", "password": PASSWORD + "x" * 4096},
    ]
    for body in secret_bodies:
        response = await client.put(url, headers=ajax.owner, json=body)
        refused(response, 422, "validation_failed")
        assert PASSWORD not in response.text
    assert [
        p["id"] for p in (await client.get("/v1/agent-projects", headers=ajax.owner)).json()
    ] == [str(agent_project_id)]
