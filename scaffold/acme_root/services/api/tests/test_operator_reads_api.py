"""The operators' reads of benchmarks and a tenant's ledger over the live
app, in memory: a read operator reads a scenario's runs, the newest first,
one run with every trial, and the ledger of the tenant it names; a tenant's
credential reaches none of them."""

from uuid import UUID

import httpx
from api_support import enrol_operator
from contracts.benchmark_storage import make_trials, operator

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.billing.root import build_billing
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
    (entry,) = ledger.json()
    assert entry["kind"] == "grant" and entry["id"] == str(grant.id)
    assert (entry["units"], entry["reason"], entry["by"]) == (
        500,
        "a pilot",
        str(granter.identity_id),
    )
    charges = await client.get(f"/v1/admin/orgs/{org_id}/ledger?kind=charge", headers=reader)
    assert charges.status_code == 200 and charges.json() == []
    other = await client.get(f"/v1/admin/orgs/{UUID(int=7)}/ledger", headers=reader)
    assert other.status_code == 200 and other.json() == []

    as_tenant = await client.get(f"/v1/admin/orgs/{org_id}/ledger", headers=owner)
    assert as_tenant.status_code == 401, as_tenant.text
    unknown = await client.get(f"/v1/admin/orgs/{org_id}/ledger?kind=gift", headers=reader)
    assert unknown.status_code == 422, unknown.text
