"""The tenant's retention over the live app, in memory: an owner or an admin
erases one session's content, which then reads as its shape alone, and
writes the tenant's policy, which the sweep holds existing sessions to. A
member erases and writes nothing; another tenant reaches neither the
session nor the policy."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, build_container, seed_request
from contracts.step_storage import (
    make_request,
    make_response,
    make_tool_request,
    make_tool_response,
)
from tenant_support import Headers, person, refused, tenant

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.context import Role
from acme.services.api.container import AppContainer

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
)
SAID = "the pump log shows a pressure spike at 14:02"
SHAPE = ["message", "model_request", "model_response", "tool_request", "tool_response"]


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


async def org_of(container: AppContainer) -> UUID:
    org = await container.storage.get_tenancy_storage().read_org_by_slug("ajax")
    assert org is not None
    return org.id


async def session_saying(
    client: httpx.AsyncClient, container: AppContainer, owner: Headers
) -> str:
    """A session with a whole turn: what a person said, the model's call and
    answer, and a tool's call and result."""
    started = await client.post(
        "/v1/agent-sessions",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"kind": "assistant", "title": "the dropped object", "project_id": PROJECT_ID},
    )
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    said = await client.post(
        f"/v1/agent-sessions/{session_id}/messages",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"text": SAID},
    )
    assert said.status_code == 201, said.text
    managers = container.managers
    ctx = await managers.tenancy.authenticate(
        seed_request(), owner["Authorization"].removeprefix("Bearer ")
    )
    sid, loop_id = UUID(session_id), UUID(said.json()["loop_id"])
    request = make_request(sid, loop_id, (UUID(said.json()["id"]),))
    response = make_response(sid, loop_id, request.id)
    call = make_tool_request(sid, loop_id, response.id)
    answer = make_tool_response(sid, loop_id, call.id)
    epoch = await managers.steps.begin_run(ctx, sid)
    await managers.steps.append_steps(ctx, sid, epoch, [request, response, call, answer])
    return session_id


async def steps_of(client: httpx.AsyncClient, owner: Headers, session_id: str) -> list[Any]:
    read = await client.get(f"/v1/agent-sessions/{session_id}/steps", headers=owner)
    assert read.status_code == 200, read.text
    return read.json()["items"]


def shape_of(steps: list[Any]) -> list[tuple[int, str, str]]:
    return [(step["seq"], step["type"], step["id"]) for step in steps]


def at(headers: Headers, version: int) -> Headers:
    return {**headers, "If-Match": f'"{version}"'}


async def test_an_admin_erases_a_sessions_content_and_its_shape_stays(
    client: httpx.AsyncClient, owner: Headers, container: AppContainer
) -> None:
    """After the erasure, every step keeps its place, its type, and its id,
    and says nothing; the key is revoked and every version of it destroyed;
    a second call answers as the first left it."""
    admin = await person(client, container, await org_of(container), Role.ADMIN)
    session_id = await session_saying(client, container, owner)
    before = await steps_of(client, owner, session_id)
    assert [step["type"] for step in before] == SHAPE
    assert before[0]["text"] == SAID

    erased = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=admin)

    assert erased.status_code == 200, erased.text
    assert erased.json()["session_id"] == session_id
    assert erased.json()["content_expired_at"] is not None
    after = await steps_of(client, owner, session_id)
    assert shape_of(after) == shape_of(before)
    assert {step["text"] for step in after} == {""}
    assert SAID not in str(after)
    ring = await container.storage.get_privacy_storage().read_keys(
        await org_of(container), UUID(session_id)
    )
    assert ring.keys and ring.revoked and all(key.is_destroyed() for key in ring.keys)
    again = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=owner)
    assert again.status_code == 200, again.text
    assert again.json() == erased.json()


async def test_an_admin_writes_the_policy_and_the_sweep_holds_sessions_to_it(
    client: httpx.AsyncClient, owner: Headers, container: AppContainer
) -> None:
    """The first write names no version; each after names the one read. A
    tightening to keep nothing at rest reaches a session created before it
    at the next sweep: its content goes, and its shape stays."""
    admin = await person(client, container, await org_of(container), Role.ADMIN)
    session_id = await session_saying(client, container, owner)
    loosest = await client.get("/v1/retention/policy", headers=admin)
    assert loosest.status_code == 200, loosest.text
    assert loosest.json()["version"] == 0
    assert loosest.json()["policy"]["content_lifetime"] is None

    first = await client.put(
        "/v1/retention/policy", headers=admin, json={"policy": {"content_lifetime": "P30D"}}
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["policy"]["content_lifetime"] == "P30D"
    again = await client.put("/v1/retention/policy", headers=admin, json={"policy": {}})
    refused(again, 412, "precondition_failed")
    stale = await client.put("/v1/retention/policy", headers=at(admin, 2), json={"policy": {}})
    refused(stale, 412, "precondition_failed")
    malformed = await client.put(
        "/v1/retention/policy",
        headers=at(admin, 1),
        json={"policy": {"content_lifetime": "P30D", "shape_lifetime": "P7D"}},
    )
    refused(malformed, 422, "validation_failed")
    tightened = await client.put(
        "/v1/retention/policy",
        headers=at(admin, 1),
        json={"policy": {"content_lifetime": "P30D", "storage_mode": "memory_only"}},
    )
    assert tightened.status_code == 200, tightened.text
    assert tightened.json()["version"] == 2
    assert (await steps_of(client, owner, session_id))[0]["text"] == SAID

    await container.managers.retention.sweep(seed_request())

    after = await steps_of(client, owner, session_id)
    assert [step["type"] for step in after] == SHAPE
    assert {step["text"] for step in after} == {""}
    read = await client.get("/v1/retention/policy", headers=owner)
    assert read.json() == tightened.json()


async def test_a_member_erases_and_writes_nothing(
    client: httpx.AsyncClient, owner: Headers, container: AppContainer
) -> None:
    session_id = await session_saying(client, container, owner)
    for role in (Role.MEMBER, Role.VIEWER):
        headers = await person(client, container, await org_of(container), role)
        erased = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=headers)
        refused(erased, 403, "not_authorized")
        written = await client.put(
            "/v1/retention/policy", headers=headers, json={"policy": {"content_lifetime": "P1D"}}
        )
        refused(written, 403, "not_authorized")
        assert (await client.get("/v1/retention/policy", headers=headers)).status_code == 200
    assert (await steps_of(client, owner, session_id))[0]["text"] == SAID
    assert (await client.get("/v1/retention/policy", headers=owner)).json()["version"] == 0


async def test_another_tenant_reaches_neither_the_session_nor_the_policy(
    client: httpx.AsyncClient, owner: Headers, container: AppContainer
) -> None:
    """Another tenant's owner erasing a session that exists gets the 404 an
    unknown id gets, and its policy write is its own tenant's alone."""
    session_id = await session_saying(client, container, owner)
    bravo = await tenant(client, container, "bravo")

    crossed = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=bravo.owner)
    missing = await client.post(f"/v1/retention/sessions/{UUID(int=7)}/erase", headers=bravo.owner)
    refused(crossed, 404, "not_found")
    refused(missing, 404, "not_found")
    written = await client.put(
        "/v1/retention/policy",
        headers=bravo.owner,
        json={"policy": {"content_lifetime": "P1D", "storage_mode": "memory_only"}},
    )
    assert written.status_code == 200, written.text
    await container.managers.retention.sweep(seed_request())

    assert (await steps_of(client, owner, session_id))[0]["text"] == SAID
    ours = await client.get("/v1/retention/policy", headers=owner)
    assert ours.json()["version"] == 0 and ours.json()["policy"]["storage_mode"] == "sealed"
