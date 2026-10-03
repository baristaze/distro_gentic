"""The model matrix over the live app, in memory. A tenant on its own keys
reads what it may choose, the published matrix's fills from the providers
it holds a key for, and chooses and drops a fill; one the platform pays for
chooses nothing. An operator who may write stages and publishes a version,
which publishes only once its fills qualify; a read operator and a tenant
do neither."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import OWNER, build_container, enrol_operator, seed_request, sign_in_as
from contracts.benchmark_storage import operator

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.billing.root import build_billing
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.context import OperatorRole, TenantContext
from acme.om.matrix.root import MatrixLayer
from acme.om.matrix.types.record import BenchmarkRun
from acme.om.models.types.fill import MAIN, SUMMARIZER
from acme.om.platform_agents.kinds import SHIPPED
from acme.services.api.container import AppContainer
from acme.services.api.seed import seed_matrix

SONNET: dict[str, Any] = {
    "provider": "anthropic",
    "model": "claude-sonnet-5-5",
    "effort": "high",
    "max_output_tokens": 32_000,
    "context_window": 200_000,
}
"""A fill no version names until a case stages it."""

OPUS: dict[str, Any] = {**SONNET, "model": "claude-opus-5-5"}


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, model_providers="scripted")


async def tenant_on(
    client: httpx.AsyncClient, container: AppContainer, funding: FundingMode, slug: str
) -> tuple[TenantContext, dict[str, str]]:
    """An org whose account opens on `funding`, and its owner's headers."""
    email = f"{slug}@example.test"
    ctx, org = await container.managers.tenancy.bootstrap(
        seed_request(), slug.title(), slug, email, OWNER["name"]
    )
    billing = build_billing(container.storage, container.managers, PaymentProviderTwinImpl())
    own = funding is FundingMode.OWN_KEY
    await billing.open_account(
        ctx,
        AccountRequest(
            funding=funding, key_ref="own-keys" if own else None, plan_id="starter", zone="UTC"
        ),
    )
    return ctx, await sign_in_as(client, email, org.id)


async def test_a_tenant_on_its_own_keys_chooses_only_among_its_options(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    await seed_matrix(container.storage, container.managers, seed_request(), ())
    _, owner = await tenant_on(client, container, FundingMode.OWN_KEY, "ajax")
    keyless_options = (await client.get("/v1/matrix/options", headers=owner)).json()
    assert keyless_options and all(option["fills"] == [] for option in keyless_options), (
        "no key, nothing to choose"
    )
    saved = await client.put(
        "/v1/provider-keys/anthropic", headers=owner, json={"value": "sk-ant-own"}
    )
    assert saved.status_code == 200, saved.text

    options = (await client.get("/v1/matrix/options", headers=owner)).json()
    by_role = {option["role"]: option["fills"] for option in options}
    assert {"main", "summarizer"} <= set(by_role)
    assert all(fill["provider"] == "anthropic" for fills in by_role.values() for fill in fills)
    (main,) = by_role["main"]
    assert main["model"] == "claude-sonnet-5-5"

    chosen = await client.put("/v1/matrix/choices/main", headers=owner, json={"fill": main})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["role"] == "main" and chosen.json()["fill"] == main
    choices = (await client.get("/v1/matrix/choices", headers=owner)).json()
    assert [choice["id"] for choice in choices] == [chosen.json()["id"]]

    # A fill the matrix never qualified for the role, and one from a
    # provider it holds no key for, are refused.
    unqualified = await client.put("/v1/matrix/choices/main", headers=owner, json={"fill": OPUS})
    assert unqualified.status_code == 422, unqualified.text
    keyless = {**main, "provider": "openai", "model": "gpt-6.1-sol"}
    refused = await client.put("/v1/matrix/choices/main", headers=owner, json={"fill": keyless})
    assert refused.status_code == 422 and "no live openai key" in refused.text

    dropped = await client.delete("/v1/matrix/choices/main", headers=owner)
    assert dropped.status_code == 204, dropped.text
    assert (await client.get("/v1/matrix/choices", headers=owner)).json() == []
    again = await client.delete("/v1/matrix/choices/main", headers=owner)
    assert again.status_code == 404, again.text


async def test_a_tenant_the_platform_pays_for_chooses_nothing(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    await seed_matrix(container.storage, container.managers, seed_request(), ())
    _, owner = await tenant_on(client, container, FundingMode.PLATFORM, "brio")
    assert (await client.get("/v1/matrix/options", headers=owner)).json() == []
    fill = {**SONNET, "context_window": 400_000}
    refused = await client.put("/v1/matrix/choices/main", headers=owner, json={"fill": fill})
    assert refused.status_code == 422 and "own keys" in refused.text


def a_version(*fills: dict[str, Any]) -> dict[str, Any]:
    """Every model role a version must serve, each answered by the row that
    matches every question."""
    roles = sorted({MAIN, SUMMARIZER, *(role for kind in SHIPPED for role in kind.roles)})
    return {"roles": roles, "rows": [{"fills": list(fills)}]}


async def test_an_operator_publishes_a_version_once_its_fills_qualify(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    writer, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    staged = await client.post("/v1/admin/matrix/versions", headers=writer, json=a_version(OPUS))
    assert staged.status_code == 201, staged.text
    version = staged.json()
    assert (version["number"], version["status"]) == (1, "pending")
    assert version["rows"][0]["matches"]["role"] is None

    unqualified = await client.post("/v1/admin/matrix/versions/1/publish", headers=writer)
    assert unqualified.status_code == 422, unqualified.text
    assert "no passing benchmark" in unqualified.json()["error"]["message"]
    assert (
        await client.get("/v1/admin/matrix/versions/current", headers=writer)
    ).status_code == 404

    operators = MatrixLayer(container.storage).build(container.managers).matrix_operator
    for role in version["roles"]:
        run = BenchmarkRun(
            provider=OPUS["provider"],
            model=OPUS["model"],
            role=role,
            benchmark="swe-lite",
            passed=True,
            run="run-1",
        )
        await operators.record_benchmark(operator(), run)
    published = await client.post("/v1/admin/matrix/versions/1/publish", headers=writer)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    current = await client.get("/v1/admin/matrix/versions/current", headers=writer)
    assert current.json()["id"] == version["id"]
    twice = await client.post("/v1/admin/matrix/versions/1/publish", headers=writer)
    assert twice.status_code == 412, twice.text


async def test_staging_and_publishing_need_the_operators_write_and_a_tenant_reaches_neither(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    await seed_matrix(container.storage, container.managers, seed_request(), ())
    reader, _ = await enrol_operator(client, container, "sup@example.test", OperatorRole.READ)
    writer, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    staged = await client.post("/v1/admin/matrix/versions", headers=writer, json=a_version(OPUS))
    number = staged.json()["number"]

    for headers, status in ((owner, 401), (reader, 403)):
        stage = await client.post(
            "/v1/admin/matrix/versions", headers=headers, json=a_version(SONNET)
        )
        assert stage.status_code == status, stage.text
        publish = await client.post(f"/v1/admin/matrix/versions/{number}/publish", headers=headers)
        assert publish.status_code == status, publish.text
    read = await client.get(f"/v1/admin/matrix/versions/{number}", headers=reader)
    assert read.status_code == 200 and read.json()["status"] == "pending"
    tenant_read = await client.get(f"/v1/admin/matrix/versions/{number}", headers=owner)
    assert tenant_read.status_code == 401, tenant_read.text
    # The refused writes landed nothing: the seed's version is the matrix,
    # and the writer's is the only one staged since.
    current = (await client.get("/v1/admin/matrix/versions/current", headers=reader)).json()
    assert current["number"] == number - 1
    later = await client.get(f"/v1/admin/matrix/versions/{number + 1}", headers=reader)
    assert later.status_code == 404, later.text


async def test_a_staged_shape_it_may_not_have_is_refused(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    writer, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    twice = a_version(OPUS, OPUS)
    refused = await client.post("/v1/admin/matrix/versions", headers=writer, json=twice)
    assert refused.status_code == 422, refused.text
    window = a_version({**OPUS, "max_output_tokens": 300_000})
    refused = await client.post("/v1/admin/matrix/versions", headers=writer, json=window)
    assert refused.status_code == 422, refused.text
    unserved = a_version(OPUS)
    unserved["rows"].append({"matches": {"role": "triage"}, "fills": [OPUS]})
    refused = await client.post("/v1/admin/matrix/versions", headers=writer, json=unserved)
    assert refused.status_code == 422, refused.text
