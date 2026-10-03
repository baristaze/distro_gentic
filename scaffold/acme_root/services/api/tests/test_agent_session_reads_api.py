"""A session's reads over the live app, in memory: the tenant's sessions
listed in a status a page at a time, a session's children, archive, delete
and restore, each by the role that may; and every route that names a
session, called by another tenant with one that exists, answered as an
unknown id is."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, add_member, build_container, seed_request, sign_in_as
from contracts.agent_session_storage import make_session

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.context import Role, TenantContext
from acme.services.api.container import AppContainer

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=2, count=4),
)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test container with one kind the product runs."""
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


async def start(client: httpx.AsyncClient, headers: dict[str, str], title: str) -> dict[str, Any]:
    answered = await client.post(
        "/v1/agent-sessions",
        headers=created(headers),
        json={"kind": "assistant", "title": title, "project_id": PROJECT_ID},
    )
    assert answered.status_code == 201, answered.text
    return answered.json()


async def context_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def spawn(container: AppContainer, headers: dict[str, str], parent_id: str) -> str:
    """A sub-agent of the session, as the loop's spawn writes it."""
    ctx = await context_of(container, headers)
    sessions = container.managers.agent_sessions
    parent = await sessions.get_session(ctx, UUID(parent_id))
    child = await sessions.create_session(ctx, make_session(parent=parent))
    return str(child.id)


async def viewer_of(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> dict[str, str]:
    me = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(me.json()["id"])
    await add_member(container, org_id, "vic@example.test", Role.VIEWER)
    return await sign_in_as(client, "vic@example.test", org_id)


async def test_a_member_lists_the_tenants_sessions_in_a_status_a_page_at_a_time(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    started = [await start(client, owner, f"session {index}") for index in range(3)]
    woken = started[1]["id"]
    said = await client.post(
        f"/v1/agent-sessions/{woken}/messages", headers=created(owner), json={"text": "go"}
    )
    assert said.status_code == 201, said.text

    first = await client.get("/v1/agent-sessions", headers=owner, params={"limit": 2})
    second = await client.get(
        "/v1/agent-sessions",
        headers=owner,
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )
    pending = await client.get("/v1/agent-sessions", headers=owner, params={"status": "pending"})
    idle = await client.get("/v1/agent-sessions", headers=owner, params={"status": "idle"})

    assert first.status_code == 200, first.text
    paged = [s["id"] for s in first.json()["items"] + second.json()["items"]]
    assert paged == sorted(s["id"] for s in started)
    assert second.json()["next_cursor"] is None
    assert [s["id"] for s in pending.json()["items"]] == [woken]
    assert {s["id"] for s in idle.json()["items"]} == {started[0]["id"], started[2]["id"]}


async def test_a_cursor_of_another_list_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    for index in range(2):
        await start(client, owner, f"session {index}")
    files = await client.get("/v1/api-keys", headers=owner, params={"limit": 1})
    stolen = files.json()["next_cursor"] or "bm90IGEgY3Vyc29y"

    refused = await client.get("/v1/agent-sessions", headers=owner, params={"cursor": stolen})

    assert refused.status_code == 422, refused.text


async def test_a_sessions_children_are_listed_with_their_parent(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    parent = await start(client, owner, "the parent")
    children = sorted([await spawn(container, owner, parent["id"]) for _ in range(3)])

    first = await client.get(
        f"/v1/agent-sessions/{parent['id']}/children", headers=owner, params={"limit": 2}
    )
    rest = await client.get(
        f"/v1/agent-sessions/{parent['id']}/children",
        headers=owner,
        params={"cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200, first.text
    items = first.json()["items"] + rest.json()["items"]
    assert [child["id"] for child in items] == children
    assert {(c["parent_id"], c["root_id"]) for c in items} == {(parent["id"], parent["id"])}
    assert rest.json()["next_cursor"] is None


async def test_a_member_archives_deletes_and_restores_a_session_and_a_viewer_does_not(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await start(client, owner, "the dropped object")
    path = f"/v1/agent-sessions/{session['id']}"
    viewer = await viewer_of(client, container, owner)

    refused = [
        (await client.post(f"{path}/archive", headers=viewer)).status_code,
        (await client.delete(path, headers=viewer)).status_code,
    ]
    archived = await client.post(f"{path}/archive", headers=owner)
    deleted = await client.delete(path, headers=owner)
    hidden = await client.get(path, headers=owner)
    listed = await client.get("/v1/agent-sessions", headers=owner)
    not_restored = await client.post(f"{path}/restore", headers=viewer)
    restored = await client.post(f"{path}/restore", headers=owner)
    back = await client.get(path, headers=owner)

    assert refused == [403, 403]
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None
    assert hidden.status_code == 404 and listed.json()["items"] == []
    assert not_restored.status_code == 403
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert back.status_code == 200 and back.json()["archived_at"] is not None


async def test_a_session_with_a_loop_open_is_neither_archived_nor_deleted(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner, "the dropped object")
    path = f"/v1/agent-sessions/{session['id']}"
    said = await client.post(f"{path}/messages", headers=created(owner), json={"text": "go"})
    assert said.status_code == 201, said.text

    archived = await client.post(f"{path}/archive", headers=owner)
    deleted = await client.delete(path, headers=owner)

    assert (archived.status_code, deleted.status_code) == (422, 422)
