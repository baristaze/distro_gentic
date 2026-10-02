"""Stations over the live app, in memory: a lab, a pool, and a station, with
no limit of the station's anywhere on the wire; a lab daemon that calls
with a credential of its own kind and nothing else; a session that joins
a line parked and is granted at once; and a job under its lease that the
daemon claims naming nothing but the version it reads, renews, and
reports, its refused command recorded in the run."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import seed_request
from contracts.agent_session_storage import make_session
from contracts.step_storage import make_message, make_request

from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.hosts import rules
from acme.om.hosts.rules import WireType
from acme.om.stations.rules import LINE_PARK
from acme.services.api.container import AppContainer

DAEMON_APP = {"X-App": "api", "X-App-Version": "station-daemon@test"}


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **DAEMON_APP}


async def tenant_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def a_lab(client: httpx.AsyncClient, owner: dict[str, str]) -> dict[str, Any]:
    lab = await client.post("/v1/labs", headers=created(owner), json={"name": "lab-1"})
    assert lab.status_code == 201, lab.text
    pool = await client.post("/v1/station-pools", headers=created(owner), json={"name": "pool-1"})
    assert pool.status_code == 201, pool.text
    station = await client.post(
        "/v1/stations",
        headers=created(owner),
        json={
            "lab_id": lab.json()["id"],
            "pool_id": pool.json()["id"],
            "name": "station-1",
            "capabilities": ["arm"],
        },
    )
    assert station.status_code == 201, station.text
    return {"lab": lab.json()["id"], "pool": pool.json()["id"], "station": station.json()["id"]}


async def a_daemon(client: httpx.AsyncClient, owner: dict[str, str], lab_id: str) -> str:
    issued = await client.post(f"/v1/labs/{lab_id}/daemon-credentials", headers=owner)
    assert issued.status_code == 200, issued.text
    assert issued.json()["lab_id"] == lab_id
    return issued.json()["token"]


async def a_waiting_session(container: AppContainer, ctx: TenantContext) -> UUID:
    """A session whose loop parked on the line, as the loop parks it."""
    sessions, steps = container.managers.agent_sessions, container.managers.steps
    session = await sessions.create_session(ctx, make_session())
    (message,) = await steps.append_inputs(ctx, session.id, [make_message(session.id)])
    epoch = await steps.begin_run(ctx, session.id)
    await steps.append_steps(
        ctx, session.id, epoch, [make_request(session.id, message.id, (message.id,))]
    )
    await sessions.park(ctx, session.id, epoch, message.id, LINE_PARK)
    return session.id


async def test_no_limit_of_a_station_travels_on_the_wire(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    made = await a_lab(client, owner)
    with_limits = await client.post(
        "/v1/stations",
        headers=created(owner),
        json={
            "lab_id": made["lab"],
            "pool_id": made["pool"],
            "name": "station-2",
            "limits": {"speed": {"max": 100}},
        },
    )
    assert with_limits.status_code == 422, with_limits.text
    listed = await client.get(f"/v1/station-pools/{made['pool']}/stations", headers=owner)
    assert listed.status_code == 200
    assert not [key for station in listed.json() for key in station if "limit" in key]


async def test_a_daemon_calls_with_a_credential_of_its_own_and_nothing_else(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    made = await a_lab(client, owner)
    first = await a_daemon(client, owner, made["lab"])
    assert first.startswith("std_")
    # It opens no tenant route, and nothing but it opens a daemon's.
    tenant_route = await client.get(f"/v1/station-pools/{made['pool']}/line", headers=bearer(first))
    assert tenant_route.status_code == 401, tenant_route.text
    for credential in (owner["Authorization"].removeprefix("Bearer "), "hst_forged"):
        refused = await client.post(
            "/v1/station-daemon/claims", headers=bearer(credential), json={"station_version": 1}
        )
        assert refused.status_code == 401, refused.text
    own = await client.post("/v1/station-daemon/credentials", headers=bearer(first))
    assert own.status_code == 200, own.text
    assert own.json()["token"] != first and own.json()["lab_id"] == made["lab"]
    revoked = await client.delete(f"/v1/labs/{made['lab']}/daemon-credentials", headers=owner)
    assert revoked.status_code == 200 and revoked.json()["credentials_ended"] == 2
    after = await client.post(
        "/v1/station-daemon/claims",
        headers=bearer(own.json()["token"]),
        json={"station_version": 1},
    )
    assert after.status_code == 401, after.text


async def test_a_granted_session_sends_a_job_and_its_daemon_claims_renews_and_reports_it(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = await a_lab(client, owner)
    daemon = await a_daemon(client, owner, made["lab"])
    session = await a_waiting_session(container, await tenant_of(container, owner))
    joined = await client.post(
        f"/v1/station-pools/{made['pool']}/line",
        headers=created(owner),
        json={
            "session_id": str(session),
            "capabilities": ["arm"],
            "project": "acme/firmware",
            "candidate": "4f0405f",
            "procedure": "smoke",
            "procedure_version": "v1",
        },
    )
    assert joined.status_code == 201, joined.text
    assert joined.json()["entry"]["state"] == "granted"
    lease_id = joined.json()["entry"]["lease_id"]
    sent = await client.post(
        f"/v1/station-leases/{lease_id}/jobs",
        headers=created(owner),
        json={
            "commands": [
                {"operation": "apply", "parameters": {"speed": 0.5}},
                {"operation": "apply", "parameters": {"speed": 9.0}},
            ]
        },
    )
    assert sent.status_code == 201, sent.text
    job = sent.json()
    assert (job["fencing_token"], job["procedure"], job["candidate"]) == (1, "smoke", "4f0405f")
    # The claim names the version it reads and nothing else.
    asking = await client.post(
        "/v1/station-daemon/claims",
        headers=bearer(daemon),
        json={"station_version": 1, "lab_id": made["lab"]},
    )
    assert asking.status_code == 422, asking.text
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.STATION, 2)
    stale = await client.post(
        "/v1/station-daemon/claims", headers=bearer(daemon), json={"station_version": 1}
    )
    assert stale.status_code == 426, stale.text
    monkeypatch.setitem(rules.WIRE_FLOOR, WireType.STATION, 1)
    claimed = await client.post(
        "/v1/station-daemon/claims", headers=bearer(daemon), json={"station_version": 1}
    )
    assert claimed.status_code == 200, claimed.text
    answer = claimed.json()
    assert answer["item"]["kind"] == "STATION" and answer["job"]["id"] == job["id"]
    assert answer["lease_seconds"] > 0
    renewed = await client.post(
        f"/v1/station-daemon/jobs/{job['id']}/renewals", headers=bearer(daemon)
    )
    assert renewed.status_code == 200 and renewed.json()["fencing_token"] == 1
    now = utcnow().isoformat()
    report = {
        "run_id": str(uuid4()),
        "outcome": "passed",
        "started_at": now,
        "finished_at": now,
        "commands_run": 1,
        "cases": {"passed": 1},
        "refused": [
            {
                "operation": "apply",
                "reason": "limit",
                "detail": "speed: 9.0 is above 1.0, past station-1's limit",
                "refused_at": now,
            }
        ],
        "adapter": "twin:station-1",
        "provenance": "twin",
        "daemon_version": "station-daemon@test",
    }
    # A run with a refused command is aborted, and says what stopped it.
    passed = await client.post(
        f"/v1/station-daemon/jobs/{job['id']}/reports", headers=bearer(daemon), json=report
    )
    assert passed.status_code == 422, passed.text
    report |= {"outcome": "aborted", "abort": "limit: speed: 9.0 is above 1.0"}
    reported = await client.post(
        f"/v1/station-daemon/jobs/{job['id']}/reports", headers=bearer(daemon), json=report
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["state"] == "finished"
    assert reported.json()["run_id"] == report["run_id"]
    ctx = await tenant_of(container, owner)
    (run,) = (await container.managers.evidence.get_runs(ctx, session, None, 10)).items
    assert str(run.id) == report["run_id"] and run.outcome.value == "aborted"
    assert run.metrics["refused"][0]["detail"].startswith("speed: 9.0")
