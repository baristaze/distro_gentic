"""A tenant's budgets over the API: an owner sets one over a person, a
project, or the tenant, in native tokens or reference cost, lists it, and
the gate holds every call charged to its scope to it. A member sets none
and changes no amount; another tenant's budget is not found, a tenant key
naming another tenant is refused, and a budget another tenant sets binds
nothing here."""

from uuid import UUID

import httpx
import pytest
from api_support import seed_request
from tenant_support import person, refused, tenant

from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.billing.root import build_billing
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.budgets.types.amount import AmountUnit, Spend
from acme.om.budgets.types.breach import Refusal
from acme.om.budgets.types.hold import Hold, HoldRequest
from acme.om.context import Role, TenantContext
from acme.om.windows.impl.gate import scopes_of
from acme.services.api.container import AppContainer

Headers = dict[str, str]


async def context_of(container: AppContainer, headers: Headers) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def funded(container: AppContainer, headers: Headers) -> TenantContext:
    """The owner's context, its tenant's account open, so the gate has
    someone to charge."""
    ctx = await context_of(container, headers)
    billing = build_billing(container.storage, container.managers, PaymentProviderTwinImpl())
    request = AccountRequest(
        funding=FundingMode.PLATFORM, key_ref=None, plan_id="starter", zone="UTC"
    )
    await billing.open_account(ctx, request)
    return ctx


async def asked(
    container: AppContainer, ctx: TenantContext, tokens: int, project_id: UUID | None
) -> Hold | Refusal:
    """A model call of a session of the caller's, charged to the scopes the
    session runner charges it to, whose worst case is `tokens`."""
    spender = Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)
    request = HoldRequest(
        spender_id=ctx.user_id,
        scopes=scopes_of(ctx.org_id, new_id(), new_id(), spender, project_id=project_id),
        exposure=Spend(cost_micros=1_000, tokens=tokens),
        own=None,
        purpose="main",
    )
    return await container.managers.budget_gate.authorize(ctx, request)


def breached(answer: Hold | Refusal, budget_id: str) -> set[AmountUnit]:
    assert isinstance(answer, Refusal), answer
    return {b.unit for b in answer.breaches if str(b.budget_id) == budget_id}


@pytest.mark.parametrize("kind", ["person", "project", "tenant"])
async def test_an_owner_sets_a_token_budget_lists_it_and_the_gate_holds_calls_to_it(
    client: httpx.AsyncClient, container: AppContainer, kind: str
) -> None:
    ajax = await tenant(client, container, "ajax")
    ctx = await funded(container, ajax.owner)
    project_id = new_id()
    key = {"person": str(ctx.user_id), "project": str(project_id), "tenant": None}[kind]
    body = {"scope_kind": kind, "scope_key": key, "window_kind": "day", "tokens": 3_000}

    made = await client.post("/v1/budgets", headers=ajax.owner, json=body)

    assert made.status_code == 201, made.text
    budget = made.json()
    expected_key = {"person": key, "project": key, "tenant": str(ajax.org_id)}[kind]
    assert (budget["scope_kind"], budget["scope_key"]) == (kind, expected_key)
    assert (budget["window_kind"], budget["tokens"], budget["cost_micros"]) == ("day", 3_000, None)
    listed = await client.get("/v1/budgets", headers=ajax.owner)
    assert [b["id"] for b in listed.json()] == [budget["id"]]
    got = await client.get(f"/v1/budgets/{budget['id']}", headers=ajax.owner)
    assert got.json() == budget
    past = await asked(container, ctx, 4_000, project_id)
    assert breached(past, budget["id"]) == {AmountUnit.TOKENS}, "a call past it is refused"
    within = await asked(container, ctx, 2_000, project_id)
    assert isinstance(within, Hold), within
    assert budget["id"] in {str(line.budget_id) for line in within.lines}, "a fit is held on it"


async def test_a_budget_in_reference_cost_over_a_span_reads_back_as_set(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    body = {
        "scope_kind": "tenant",
        "window_kind": "span",
        "window_seconds": 3_600,
        "cost_micros": 5_000_000,
    }
    made = await client.post("/v1/budgets", headers=ajax.owner, json=body)
    assert made.status_code == 201, made.text
    assert (made.json()["window_seconds"], made.json()["cost_micros"]) == (3_600, 5_000_000)


@pytest.mark.parametrize(
    "body",
    [
        {"scope_kind": "team", "scope_key": str(UUID(int=1)), "window_kind": "day", "tokens": 1},
        {"scope_kind": "session", "scope_key": str(UUID(int=1)), "window_kind": "day", "tokens": 1},
        {"scope_kind": "person", "window_kind": "day", "tokens": 1},
        {"scope_kind": "person", "scope_key": "someone", "window_kind": "day", "tokens": 1},
        {"scope_kind": "tenant", "window_kind": "day"},
        {"scope_kind": "tenant", "window_kind": "span", "tokens": 1},
        {"scope_kind": "tenant", "window_kind": "day", "window_seconds": 60, "tokens": 1},
        {"scope_kind": "tenant", "window_kind": "day", "tokens": -1},
    ],
)
async def test_a_budget_the_gate_would_not_hold_a_call_to_is_refused_whole(
    client: httpx.AsyncClient, container: AppContainer, body: dict[str, object]
) -> None:
    ajax = await tenant(client, container, "ajax")
    refused(
        await client.post("/v1/budgets", headers=ajax.owner, json=body), 422, "validation_failed"
    )
    assert (await client.get("/v1/budgets", headers=ajax.owner)).json() == []


@pytest.mark.parametrize("role", [Role.MEMBER, Role.VIEWER])
async def test_a_member_sets_no_budget_and_raises_no_amount(
    client: httpx.AsyncClient, container: AppContainer, role: Role
) -> None:
    ajax = await tenant(client, container, "ajax")
    them = await person(client, container, ajax.org_id, role)
    mine = await context_of(container, them)
    own = {"scope_kind": "person", "scope_key": str(mine.user_id), "window_kind": "day"}
    refused(
        await client.post("/v1/budgets", headers=them, json={**own, "tokens": 10**9}),
        403,
        "not_authorized",
    )
    capped = await client.post("/v1/budgets", headers=ajax.owner, json={**own, "tokens": 10})
    assert capped.status_code == 201, capped.text
    url = f"/v1/budgets/{capped.json()['id']}/amount"
    raised = await client.put(url, headers={**them, "If-Match": '"1"'}, json={"tokens": 10**9})
    refused(raised, 403, "not_authorized")
    listed = await client.get("/v1/budgets", headers=them)
    assert [b["tokens"] for b in listed.json()] == [10], "one budget, at its amount"


async def test_another_tenant_reads_nothing_and_its_budgets_bind_nothing_here(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    bolt = await tenant(client, container, "bolt")
    owner = await funded(container, ajax.owner)
    made = await client.post(
        "/v1/budgets",
        headers=ajax.owner,
        json={"scope_kind": "tenant", "window_kind": "day", "tokens": 10**6},
    )
    url = f"/v1/budgets/{made.json()['id']}"

    refused(await client.get(url, headers=bolt.owner), 404, "not_found")
    raised = await client.put(
        f"{url}/amount", headers={**bolt.owner, "If-Match": '"1"'}, json={"tokens": 1}
    )
    refused(raised, 404, "not_found")
    assert (await client.get("/v1/budgets", headers=bolt.owner)).json() == []
    theirs = {"scope_kind": "tenant", "scope_key": str(ajax.org_id), "window_kind": "day"}
    refused(
        await client.post("/v1/budgets", headers=bolt.owner, json={**theirs, "tokens": 0}),
        422,
        "validation_failed",
    )
    # A budget bolt keys on ajax's owner is bolt's: ajax's calls never meet it.
    keyed = {"scope_kind": "person", "scope_key": str(owner.user_id), "window_kind": "day"}
    zero = await client.post("/v1/budgets", headers=bolt.owner, json={**keyed, "tokens": 0})
    assert zero.status_code == 201, zero.text
    assert isinstance(await asked(container, owner, 1_000, None), Hold)
    listed = await client.get("/v1/budgets", headers=ajax.owner)
    assert [b["id"] for b in listed.json()] == [made.json()["id"]]
