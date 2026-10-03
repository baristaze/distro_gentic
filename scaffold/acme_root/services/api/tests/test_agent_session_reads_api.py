"""A session's reads over the live app, in memory: the tenant's sessions
listed in a status a page at a time, a session's children, archive, delete
and restore, each by the role that may; what a session asks of a person
and the calls it holds, per session and across the tenant; its bounds, its
tool calls, and its usage; and every route that names a session, called
by another tenant with one that exists, answered as an unknown id is. No
runner works behind the API here, so a case writes a loop's steps itself,
the way a run writes them."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, add_member, build_container, seed_request, sign_in_as
from contracts.agent_session_storage import make_session
from contracts.step_storage import (
    make_request,
    make_response,
    make_tool_request,
    make_tool_response,
)

from acme.integrations.model_providers.types import Usage
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.context import Role, TenantContext
from acme.om.steps.types.header import ModelResponseHeader, Park, ParkReason
from acme.om.steps.types.step import Step
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


def used(response: Step, usage: Usage) -> Step:
    header = response.header
    assert isinstance(header, ModelResponseHeader)
    return response.model_copy(update={"header": header.model_copy(update={"usage": usage})})


async def a_loop(
    client: httpx.AsyncClient,
    container: AppContainer,
    headers: dict[str, str],
    *,
    calls: int,
    answered: int = 0,
    park: Park | None = None,
) -> dict[str, Any]:
    """A session a person spoke to, whose loop made one model call that
    asked for `calls` tool calls, the first `answered` of them answered,
    and then parked on `park`, when one is named."""
    session = await start(client, headers, "the dropped object")
    said = await client.post(
        f"/v1/agent-sessions/{session['id']}/messages",
        headers=created(headers),
        json={"text": "go"},
    )
    assert said.status_code == 201, said.text
    ctx = await context_of(container, headers)
    managers = container.managers
    sid, loop_id = UUID(session["id"]), UUID(said.json()["loop_id"])
    request = make_request(sid, loop_id, (UUID(said.json()["id"]),))
    response = used(make_response(sid, loop_id, request.id), Usage(input=100, output=20))
    steps: list[Step] = [request, response]
    for index in range(calls):
        call = make_tool_request(sid, loop_id, response.id)
        steps.append(call)
        if index < answered:
            steps.append(make_tool_response(sid, loop_id, call.id))
    epoch = await managers.steps.begin_run(ctx, sid)
    await managers.steps.append_steps(ctx, sid, epoch, steps)
    if park is not None:
        await managers.agent_sessions.park(ctx, sid, epoch, loop_id, park)
    return session


APPROVAL = Park(reason=ParkReason.PERSON, unlock="approval")
STEP_GUARD = Park(reason=ParkReason.PERSON, unlock="step_guard")


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


async def test_what_a_session_waits_on_a_person_for_is_read_per_session_and_across_the_tenant(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    holding = await a_loop(client, container, owner, calls=2, park=APPROVAL)
    asking = await a_loop(client, container, owner, calls=0, park=STEP_GUARD)
    held_at = f"/v1/agent-sessions/{holding['id']}"
    asked_at = f"/v1/agent-sessions/{asking['id']}"

    approvals = await client.get(f"{held_at}/approvals", headers=owner)
    none_asked = await client.get(f"{held_at}/questions", headers=owner)
    questions = await client.get(f"{asked_at}/questions", headers=owner)
    none_held = await client.get(f"{asked_at}/approvals", headers=owner)
    first = await client.get("/v1/approvals", headers=owner, params={"limit": 1})
    rest = await client.get(
        "/v1/approvals", headers=owner, params={"cursor": first.json()["next_cursor"]}
    )

    assert approvals.status_code == 200, approvals.text
    assert [(a["seq"], a["tool"], a["authorization_class"]) for a in approvals.json()] == [
        (4, "read_log", "read"),
        (5, "read_log", "read"),
    ]
    assert none_asked.json() == [] and none_held.json() == []
    assert questions.status_code == 200, questions.text
    assert [(q["seq"], q["unlock"]) for q in questions.json()] == [(4, "step_guard")]
    assert first.status_code == 200, first.text
    across = first.json()["items"] + rest.json()["items"]
    assert sorted((a["session_id"], a["seq"]) for a in across) == [
        (holding["id"], 4),
        (holding["id"], 5),
    ]
    assert rest.json()["next_cursor"] is None


async def test_a_sessions_tool_calls_carry_their_decision_and_answer_and_its_usage_sums(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await a_loop(client, container, owner, calls=2, answered=1, park=APPROVAL)
    path = f"/v1/agent-sessions/{session['id']}"
    decided = await client.post(
        f"{path}/calls/6/decision", headers=created(owner), json={"approve": True}
    )
    assert decided.status_code == 201, decided.text
    me = await client.get("/v1/me", headers=owner)

    calls = await client.get(f"{path}/tool-calls", headers=owner)
    after = await client.get(f"{path}/tool-calls", headers=owner, params={"after_seq": 4})
    usage = await client.get(f"{path}/usage", headers=owner)

    assert calls.status_code == 200, calls.text
    items = calls.json()["items"]
    assert [(c["seq"], c["response_seq"], c["decision"]) for c in items] == [
        (4, 5, None),
        (6, None, "approved"),
    ]
    assert items[1]["decided_by"] == me.json()["user"]["id"]
    assert [c["seq"] for c in after.json()["items"]] == [6]
    assert usage.status_code == 200, usage.text
    assert (usage.json()["calls"], usage.json()["input"], usage.json()["output"]) == (1, 100, 20)
    assert [f["fill"] for f in usage.json()["fills"]] == ["anthropic/claude-sonnet-5-5"]


async def test_a_sessions_bounds_are_its_kinds_loop_limits_and_its_trees(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner, "the dropped object")

    bounds = await client.get(f"/v1/agent-sessions/{session['id']}/bounds", headers=owner)

    assert bounds.status_code == 200, bounds.text
    body = bounds.json()
    assert (body["kind"], body["kind_version"]) == ("assistant", 1)
    assert body["loop"]["step_guard"] == 50 and body["loop"]["run_time_seconds"] == 900
    tree = body["tree"]
    assert (tree["root_id"], tree["height"], tree["count"], tree["size"]) == (
        session["id"],
        2,
        4,
        0,
    )
