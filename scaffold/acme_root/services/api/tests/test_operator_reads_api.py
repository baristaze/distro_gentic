"""The operators' reads of benchmarks and a tenant's ledger over the live
app, in memory: a read operator reads a scenario's runs, the newest first,
one run with every trial, and the ledger of the tenant it names, narrowed
to one session's entries among more than a read holds; a tenant's
credential reaches none of them."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from api_support import enrol_operator
from contracts.benchmark_storage import make_trials, operator

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.base import new_id
from acme.om.billing.impl.manager import MAX_ENTRIES
from acme.om.billing.root import build_billing
from acme.om.billing.types.ledger import Approval, Grant
from acme.om.context import OperatorRole
from acme.services.api.container import AppContainer


async def test_a_read_operator_reads_a_scenarios_trend_and_one_run(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    benchmarks = container.managers.benchmarks
    held = await benchmarks.record(operator(), make_trials([0, 0], [0, 7]))
    regressed = await benchmarks.record(operator(), make_trials([0, 3], [0, 0]))
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)

    trend = await client.get("/v1/admin/benchmarks?scenario=orders-vanish", headers=reader)
    assert trend.status_code == 200, trend.text
    assert [(run["id"], run["regressed"]) for run in trend.json()] == [
        (str(regressed.id), True),
        (str(held.id), False),
    ]
    assert "trials" not in trend.json()[0]
    one = await client.get(f"/v1/admin/benchmarks/{held.id}", headers=reader)
    assert one.status_code == 200, one.text
    assert len(one.json()["trials"]) == 4
    assert one.json()["baseline_result"]["score"] < one.json()["candidate_result"]["score"]

    for path in ("/v1/admin/benchmarks?scenario=orders-vanish", f"/v1/admin/benchmarks/{held.id}"):
        as_tenant = await client.get(path, headers=owner)
        assert as_tenant.status_code == 401, as_tenant.text
    unnamed = await client.get("/v1/admin/benchmarks", headers=reader)
    assert unnamed.status_code == 422, unnamed.text


async def test_a_read_operator_reads_the_ledger_of_the_tenant_it_names(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    billing = build_billing(container.storage, container.managers, PaymentProviderTwinImpl())
    granter = operator()
    grant = await billing.grant_units(granter, org_id, 500, "a pilot")
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)

    ledger = await client.get(f"/v1/admin/orgs/{org_id}/ledger", headers=reader)
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()["has_more"] is False
    (entry,) = ledger.json()["items"]
    assert entry["kind"] == "grant" and entry["id"] == str(grant.id)
    assert (entry["units"], entry["reason"], entry["by"]) == (
        500,
        "a pilot",
        str(granter.identity_id),
    )
    charges = await client.get(f"/v1/admin/orgs/{org_id}/ledger?kind=charge", headers=reader)
    assert charges.status_code == 200 and charges.json()["items"] == []
    other = await client.get(f"/v1/admin/orgs/{UUID(int=7)}/ledger", headers=reader)
    assert other.status_code == 200 and other.json()["items"] == []

    as_tenant = await client.get(f"/v1/admin/orgs/{org_id}/ledger", headers=owner)
    assert as_tenant.status_code == 401, as_tenant.text
    unknown = await client.get(f"/v1/admin/orgs/{org_id}/ledger?kind=gift", headers=reader)
    assert unknown.status_code == 422, unknown.text


async def test_an_operator_reads_one_sessions_entries_among_more_than_a_read_holds(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    """A tenant whose ledger holds more entries than one read answers: the
    newest read alone is cut at its limit and says so, and the operator
    reaches one session's entries by naming the session."""
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    ledger = container.storage.get_money_ledger_storage()
    by = operator().identity_id
    session_id = new_id()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    approvals = [
        await ledger.post_approval(
            org_id,
            Approval(
                id=new_id(),
                created_at=start + timedelta(seconds=n),
                session_id=session_id,
                up_to_micros=1_000,
                approved_by=by,
            ),
        )
        for n in range(2)
    ]
    # Every grant is newer than the session's entries, and there are more
    # of them than one read holds.
    for n in range(MAX_ENTRIES + 1):
        grant = Grant(
            id=new_id(),
            created_at=start + timedelta(minutes=1, seconds=n),
            units=1,
            reason="a pilot",
            granted_by=by,
        )
        await ledger.post_grant(org_id, grant)
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)
    path = f"/v1/admin/orgs/{org_id}/ledger"

    newest = await client.get(f"{path}?limit=1000", headers=reader)
    assert newest.status_code == 200, newest.text
    assert len(newest.json()["items"]) == MAX_ENTRIES and newest.json()["has_more"] is True
    assert {item["kind"] for item in newest.json()["items"]} == {"grant"}, "the session's are cut"

    session = await client.get(f"{path}?session_id={session_id}", headers=reader)
    assert session.status_code == 200, session.text
    assert session.json()["has_more"] is False
    assert [item["id"] for item in session.json()["items"]] == [
        str(approval.id) for approval in reversed(approvals)
    ]
    first = await client.get(f"{path}?session_id={session_id}&limit=1", headers=reader)
    assert [item["id"] for item in first.json()["items"]] == [str(approvals[-1].id)]
    assert first.json()["has_more"] is True
