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
from api_support import (
    PROJECT_ID,
    build_container,
    client_over,
    seed_request,
    sign_in,
    sign_in_as,
)
from contracts.step_storage import (
    make_request,
    make_response,
    make_tool_request,
    make_tool_response,
)
from tenant_support import Headers, person, refused, tenant

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import Role
from acme.services.api.container import AppContainer
from acme.services.api.seed import first_project

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
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: Headers,
    project_id: str = PROJECT_ID,
) -> str:
    """A session with a whole turn: what a person said, the model's call and
    answer, and a tool's call and result."""
    started = await client.post(
        "/v1/agent-sessions",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"kind": "assistant", "title": "the dropped object", "project_id": project_id},
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


def says_nothing(steps: list[Any]) -> bool:
    """Whether each step's content is gone from its view: no text, no
    thought, no call a model made, and no call a result answers."""
    return all(
        (step["text"], step["thinking"], step["tool_uses"]) == ("", "", [])
        and (step["type"] == "tool_request" or step["tool_use_id"] is None)
        for step in steps
    )


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
    assert before[2]["thinking"] and before[2]["tool_uses"] and before[4]["tool_use_id"]

    erased = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=admin)

    assert erased.status_code == 200, erased.text
    assert erased.json()["session_id"] == session_id
    assert erased.json()["content_expired_at"] is not None
    after = await steps_of(client, owner, session_id)
    assert shape_of(after) == shape_of(before)
    assert says_nothing(after)
    assert SAID not in str(after) and before[2]["thinking"] not in str(after)
    ring = await container.storage.get_privacy_storage().read_keys(
        await org_of(container), UUID(session_id)
    )
    assert ring.keys and ring.revoked and all(key.is_destroyed() for key in ring.keys)
    again = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=owner)
    assert again.status_code == 200, again.text
    assert again.json() == erased.json()


async def test_an_erasure_answers_with_the_report_of_a_service_that_holds_each_key(
    tmp_path: Path,
) -> None:
    """In `local`, the key service holds each session's key, destroys it, and
    reports it: the answer carries that report, its key named, no key in it."""
    container = build_container(tmp_path, agent_kinds=(ASSISTANT,), environment="local")
    async with client_over(container) as client:
        owner = await sign_in(client, container)
        session_id = await session_saying(client, container, owner)

        erased = await client.post(f"/v1/retention/sessions/{session_id}/erase", headers=owner)

        assert erased.status_code == 200, erased.text
        report = erased.json()["destruction"]
        assert report is not None and report["key_name"].endswith(session_id)
        assert set(report) == {"service", "key_name", "destroyed_at", "receipt"}


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
    assert says_nothing(after)
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


async def test_a_lifetime_past_a_century_is_refused_and_the_sweep_still_reaches_every_tenant(
    client: httpx.AsyncClient, owner: Headers, container: AppContainer
) -> None:
    """A lifetime is added to a session's creation date, which ends in year
    9999: one past a century is refused with its field named, at the tenant
    and at a project, and nothing is stored. A century is held, and the sweep
    erases another tenant's expired content."""
    ours = await session_saying(client, container, owner)
    ctx, org = await container.managers.tenancy.bootstrap(
        seed_request(), "Bravo", "bravo", "owner@bravo.test", "Bravo"
    )
    project = first_project(ctx, org.slug).model_copy(update={"id": new_id()})
    await container.storage.get_project_storage().create_project(org.id, project, ())
    bravo = await sign_in_as(client, "owner@bravo.test", org.id)
    theirs = await session_saying(client, container, bravo, str(project.id))
    kept_nothing = await client.put(
        "/v1/retention/policy", headers=bravo, json={"policy": {"storage_mode": "memory_only"}}
    )
    assert kept_nothing.status_code == 200, kept_nothing.text

    for lifetime in ("P36501D", "P9999999D"):
        for field in ("content_lifetime", "shape_lifetime"):
            policy = {field: lifetime}
            tenant_wide = await client.put(
                "/v1/retention/policy", headers=owner, json={"policy": policy}
            )
            refused(tenant_wide, 422, "validation_failed")
            assert field in tenant_wide.text, tenant_wide.text
            narrowed = await client.put(
                "/v1/retention/policy",
                headers=owner,
                json={"policy": {}, "projects": [{"project_id": PROJECT_ID, "policy": policy}]},
            )
            refused(narrowed, 422, "validation_failed")
            assert field in narrowed.text, narrowed.text
    stored = await client.get("/v1/retention/policy", headers=owner)
    assert stored.json()["version"] == 0 and stored.json()["policy"]["content_lifetime"] is None

    century = await client.put(
        "/v1/retention/policy",
        headers=owner,
        json={"policy": {"content_lifetime": "P36500D", "shape_lifetime": "P36500D"}},
    )
    assert century.status_code == 200, century.text
    await container.managers.retention.sweep(seed_request())

    assert {step["text"] for step in await steps_of(client, bravo, theirs)} == {""}
    assert (await steps_of(client, owner, ours))[0]["text"] == SAID
