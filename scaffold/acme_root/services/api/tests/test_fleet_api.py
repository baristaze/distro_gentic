"""The platform's operator routes over the live app, in memory: a tenant's
share written by an operator who may write, and on the tenant's own record;
a session's shape read under `read`, and its content opened only under a
grant the grant job writes and ends, each on the tenant's record too; and
where a session's work and a host stand, by the tenant named."""

import argparse
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import build_container, enrol_operator
from contracts.agent_session_storage import parked

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import OperatorRole
from acme.om.exceptions import NotFound
from acme.om.placement.impl.operator import SHARE_SET_KIND
from acme.om.trust.impl.operator import CONTENT_OPENED, GRANTED, REVOKED
from acme.services.api.container import AppContainer
from acme.services.api.main import granted

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
)
SAID = "the gripper drops the cup at the second waypoint"
READER = "sup@example.test"


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


@pytest.fixture
async def writer(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    headers, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    return headers


@pytest.fixture
async def reader(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    headers, _ = await enrol_operator(client, container, READER, OperatorRole.READ)
    return headers


async def org_of(client: httpx.AsyncClient, owner: dict[str, str]) -> str:
    return (await client.get("/v1/orgs/current", headers=owner)).json()["id"]


async def a_session_that_was_told(client: httpx.AsyncClient, owner: dict[str, str]) -> str:
    started = await client.post(
        "/v1/agent-sessions",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"kind": "assistant", "title": "the dropped cup"},
    )
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    said = await client.post(
        f"/v1/agent-sessions/{session_id}/messages",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"text": SAID},
    )
    assert said.status_code in (200, 201), said.text
    return session_id


async def stream(client: httpx.AsyncClient, reader: dict[str, str], org_id: str) -> list[Any]:
    answered = await client.get(f"/v1/admin/orgs/{org_id}/events?limit=200", headers=reader)
    assert answered.status_code == 200, answered.text
    return answered.json()


def job(email: str, **what: object) -> argparse.Namespace:
    """The grant job's arguments, as `acme-api grant-operator` parses them."""
    asked: dict[str, object] = {
        "email": email,
        "permission": None,
        "disable": False,
        "mint_token": None,
        "grant_content": None,
        "revoke_content": None,
        "expires_in": None,
    }
    return argparse.Namespace(**{**asked, **what})


async def test_an_operator_who_writes_sets_a_tenants_share_on_the_tenants_record(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    reader: dict[str, str],
    writer: dict[str, str],
) -> None:
    org_id = await org_of(client, owner)
    path = f"/v1/admin/orgs/{org_id}/share"
    terms = {"plan_tier": "pro", "own_lane": False, "concurrency": 3}

    refused = await client.put(path, headers=reader, json=terms)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "not_authorized"
    as_tenant = await client.put(path, headers=owner, json=terms)
    assert as_tenant.status_code == 401

    first = await client.put(path, headers=writer, json=terms)
    assert first.status_code == 200, first.text
    again = await client.put(path, headers=writer, json={**terms, "own_lane": True})
    assert again.status_code == 200, again.text
    assert (first.json()["version"], again.json()["version"]) == (1, 2)
    assert again.json()["own_lane"] is True and again.json()["plan_tier"] == "pro"
    for wrong in ({**terms, "plan_tier": "Pro Plus"}, {**terms, "concurrency": 0}):
        assert (await client.put(path, headers=writer, json=wrong)).status_code == 422
    unknown = await client.put(f"/v1/admin/orgs/{new_id()}/share", headers=writer, json=terms)
    assert unknown.status_code == 404

    me = (await client.get("/v1/admin/me", headers=writer)).json()
    written = [e for e in await stream(client, reader, org_id) if e["kind"] == SHARE_SET_KIND]
    assert [e["actor_id"] for e in written] == [me["identity_id"]] * 2


async def test_content_opens_only_under_a_grant_the_grant_job_writes_and_ends(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    reader: dict[str, str],
) -> None:
    org_id = await org_of(client, owner)
    session_id = await a_session_that_was_told(client, owner)
    base = f"/v1/admin/orgs/{org_id}/sessions/{session_id}"

    shape = await client.get(f"{base}/shape", headers=reader)
    assert shape.status_code == 200, shape.text
    assert [item["type"] for item in shape.json()["items"]][:1] == ["message"]
    assert SAID not in shape.text
    closed = await client.get(f"{base}/content", headers=reader)
    assert closed.status_code == 403 and closed.json()["error"]["code"] == "content_not_granted"

    settings = container.settings
    assert await granted(container, settings, job(READER, grant_content=UUID(org_id))) == 0
    opened = await client.get(f"{base}/content", headers=reader)
    assert opened.status_code == 200, opened.text
    assert SAID in opened.text

    assert await granted(container, settings, job(READER, revoke_content=UUID(org_id))) == 0
    again = await client.get(f"{base}/content", headers=reader)
    assert again.status_code == 403

    me = (await client.get("/v1/admin/me", headers=reader)).json()
    trail = [e for e in await stream(client, reader, org_id) if e["kind"].startswith("trust.")]
    assert [e["kind"] for e in trail] == [GRANTED, CONTENT_OPENED, REVOKED]
    assert trail[1]["actor_id"] == me["identity_id"] and trail[1]["target_id"] == session_id


async def test_the_grant_job_names_an_operator_on_the_allowlist_alone(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """A grant names the operator by the email they signed up with; an
    address no identity holds, or one off the allowlist, is refused before
    anything is written."""
    org_id = UUID(await org_of(client, owner))
    me = (await client.get("/v1/me", headers=owner)).json()
    for email in ("nobody@example.test", me["user"]["email"]):
        with pytest.raises(NotFound):
            await granted(container, container.settings, job(email, grant_content=org_id))
    with pytest.raises(NotFound):
        await granted(
            container,
            container.settings,
            job("nobody@example.test", grant_content=org_id, expires_in=60),
        )


async def test_a_sessions_standing_names_its_park_its_loop_and_its_share(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    reader: dict[str, str],
    writer: dict[str, str],
) -> None:
    org_id = await org_of(client, owner)
    session_id = await a_session_that_was_told(client, owner)
    path = f"/v1/admin/orgs/{org_id}/sessions/{session_id}/standing"

    waiting = await client.get(path, headers=reader)
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert (body["status"], body["park"], body["pending_input"]) == ("pending", None, True)
    assert (body["plan_tier"], body["share_set"], body["pool_id"]) == ("standard", False, None)
    loop = body["loop"]
    assert (loop["status"], loop["lane"], loop["ready_ahead"], loop["running_ahead"]) == (
        "queued",
        "loop:standard",
        0,
        0,
    )
    assert SAID not in waiting.text

    # The session's loop parks on the gate; the standing reads the park.
    sessions = container.storage.get_agent_session_storage()
    stored = await sessions.read_session(UUID(org_id), UUID(session_id))
    assert stored is not None
    await sessions.write_session(
        UUID(org_id), parked(stored, stored.version + 1), stored.version, ()
    )
    share = {"plan_tier": "pro", "own_lane": True, "concurrency": 2}
    assert (
        await client.put(f"/v1/admin/orgs/{org_id}/share", headers=writer, json=share)
    ).is_success
    standing = (await client.get(path, headers=reader)).json()
    assert standing["status"] == "parked"
    assert (standing["park"]["reason"], standing["park"]["unlock"]) == ("budget", "raise")
    assert (standing["plan_tier"], standing["own_lane"], standing["concurrency"]) == (
        "pro",
        True,
        2,
    )

    elsewhere = await client.get(
        f"/v1/admin/orgs/{new_id()}/sessions/{session_id}/standing", headers=reader
    )
    assert elsewhere.status_code == 404
    assert (await client.get(path, headers=owner)).status_code == 401


async def test_a_hosts_standing_names_its_state_and_what_its_lanes_hold(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    reader: dict[str, str],
) -> None:
    org_id = await org_of(client, owner)
    pool = await client.post(
        "/v1/host-pools",
        headers={**owner, "Idempotency-Key": str(uuid4())},
        json={"name": "lab", "region": "eu-west"},
    )
    pool_id = pool.json()["id"]
    issued = await client.post(f"/v1/host-pools/{pool_id}/enrollment-tokens", headers=owner)
    enrolled = await client.post(
        "/v1/hosts/enrollments",
        headers={
            "Authorization": f"Bearer {issued.json()['token']}",
            "X-App": "api",
            "X-App-Version": "host@test",
        },
        json={
            "name": "host-1",
            "advertisement": {"os": "Linux 6.8", "isolation_modes": ["container"]},
            "exec_version": 1,
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    host_id = enrolled.json()["host_id"]

    standing = await client.get(f"/v1/admin/orgs/{org_id}/hosts/{host_id}/standing", headers=reader)
    assert standing.status_code == 200, standing.text
    body = standing.json()
    assert (body["state"], body["revoked"], body["exec_version"], body["exec_floor"]) == (
        "online",
        False,
        1,
        1,
    )
    assert body["advertisement"]["isolation_modes"] == ["container"]
    assert body["lanes"] == []
    assert "host-1" not in standing.text
    elsewhere = await client.get(
        f"/v1/admin/orgs/{new_id()}/hosts/{host_id}/standing", headers=reader
    )
    assert elsewhere.status_code == 404


async def test_the_fleet_counts_carry_bounded_labels_alone(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """Every series the sweep sets is labelled by a reason, an age, a plan
    tier, or a state; a tenant's own lane is one label for every tenant."""
    org_id = await org_of(client, owner)
    await a_session_that_was_told(client, owner)
    counts = await container.managers.placement_operator.fleet_counts()
    assert {labels for count in counts.parked for labels in [count.labels]} >= {
        ("budget", "under_1h"),
        ("person", "over_1d"),
    }
    assert [(c.labels, c.value) for c in counts.loops_ready] == [(("standard",), 1)]
    assert {c.labels[0] for c in counts.hosts} == {"online", "offline", "below_floor"}
    for count in (*counts.parked, *counts.loops_ready, *counts.hosts):
        assert org_id not in count.labels
