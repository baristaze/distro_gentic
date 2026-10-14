"""Every park on the tenant's money, cleared through the API by the person
who may clear it, and the session runs again: a loop runs here in-process,
over the memory storage, the scripted model, and agent billing's gate, and parks
the way it does in use. A call far above its session's norm is approved by
a person who approves such calls, a budget a call passes is raised for its
window by a person who sets budgets, and funds that cover no call are
topped up by a payment the provider confirmed, or granted by an operator
who may write; a payment wakes every session parked on the funds, those
the payer does not see among them. Each route answers the ledger entry it posted, the session
pending with its park gone and the work that runs it queued, and the next
run goes on to its end.

Anyone else is refused, and the session stays parked: a member who may not
approve or raise, a viewer who may not pay, a payment whose signature does
not check out or that confirms another tenant's credit, and an operator who
may only read, or a tenant's person at the operators' route. A retried
approval, raise, or grant posts once."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import (
    AGENT_PROJECT_ID,
    add_member,
    build_container,
    enrol_operator,
    seed_request,
    sign_in,
    sign_in_as,
)
from contracts.loops import reply, said

from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers import ModelProvidersInterface
from acme.integrations.model_providers.calls import ModelReply
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.integrations.payments.twin import PaymentProviderTwinImpl
from acme.om.agent_billing.impl.gate import MoneyGateImpl, MoneyGateOptions
from acme.om.agent_billing.impl.pager import OperatorPagerMemoryImpl
from acme.om.agent_billing.root import build_agent_billing, build_money_gate
from acme.om.agent_billing.rules import ANOMALY_UNLOCK, FUNDS_UNLOCK, AnomalyGuard
from acme.om.agent_billing.types.spend_account import FundingMode, SpendAccountRequest
from acme.om.agent_billing.types.spend_ledger import EntryKind, FundedHold
from acme.om.agent_billing.types.unit_plan import UNIT_PLANS, UnitPlan, UnitPlanCatalog
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.budgets.types.amount import Spend
from acme.om.budgets.types.budget import BudgetScope, BudgetScopeKind
from acme.om.budgets.types.hold import Billed, HoldRequest
from acme.om.context import OperatorRole, Role, TenantContext
from acme.om.models.types.fill import MAIN
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.steps.types.header import LoopOutcome
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkKind
from acme.services.api.container import AppContainer

STEWARD = AgentKind(
    name="steward",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
)
UNIT_PLANS_HERE = UnitPlanCatalog(
    unit_plans=(
        *UNIT_PLANS.unit_plans,
        UnitPlan(id="prepaid", version=1, included_units=0, unit_price_micros=1_000),
    )
)
"""The platform's plans, and one that includes nothing: every unit it
draws is paid from a money bucket."""
GUARD = AnomalyGuard(factor=10, min_calls=3, floor_micros=0)
"""A guard that judges a session after three calls, at any cost."""
PLENTY = 100_000_000
"""A hundred of the reference currency, in millionths: far past a call."""


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


class Case:
    """A tenant whose loop calls the scripted model behind agent billing's gate,
    with its owner, an admin, a member, and a viewer signed in, and another
    tenant's owner."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        container: AppContainer,
        gate: MoneyGateImpl,
        pager: OperatorPagerMemoryImpl,
        payments: PaymentProviderTwinImpl,
        providers: ModelProvidersInterface,
    ) -> None:
        self.client = client
        self.container = container
        self.gate = gate
        self.pager = pager
        self.payments = payments
        provider = providers.get(ProviderName.ANTHROPIC)
        assert isinstance(provider, ModelProviderScriptedImpl)
        self.model = provider
        self.org_id = UUID(int=0)
        self.headers: dict[Role, dict[str, str]] = {}
        self.stranger: dict[str, str] = {}

    def __getitem__(self, role: Role) -> dict[str, str]:
        return self.headers[role]

    async def seat(self, plan: str) -> None:
        """The tenant, its account opened on `plan` and the platform's
        funding, its people signed in, and another tenant beside it."""
        owner = await sign_in(self.client, self.container)
        me = await self.client.get("/v1/orgs/current", headers=owner)
        self.org_id = UUID(me.json()["id"])
        self.headers[Role.OWNER] = owner
        for role in (Role.ADMIN, Role.MEMBER, Role.VIEWER):
            email = f"{role.value}@ajax.test"
            await add_member(self.container, self.org_id, email, role)
            self.headers[role] = await sign_in_as(self.client, email, self.org_id)
        agent_billing = build_agent_billing(
            self.container.storage,
            self.container.managers,
            self.payments,
            unit_plans=UNIT_PLANS_HERE,
        )
        request = SpendAccountRequest(
            funding=FundingMode.PLATFORM, key_ref=None, unit_plan_id=plan, zone="UTC"
        )
        await agent_billing.open_spend_account(await self.ctx(owner), request)
        _, other = await self.container.managers.tenancy.bootstrap(
            seed_request(), "Bravo", "bravo", "owner@bravo.test", "Owner"
        )
        self.stranger = await sign_in_as(self.client, "owner@bravo.test", other.id)

    async def ctx(self, headers: dict[str, str]) -> TenantContext:
        token = headers["Authorization"].removeprefix("Bearer ")
        return await self.container.managers.tenancy.authenticate(seed_request(), token)

    def say(self, *turns: ModelReply) -> None:
        self.model.add(*turns)

    async def started(self, by: Role = Role.MEMBER) -> str:
        """A session the person started and spoke to: its loop waits for a run."""
        person = self[by]
        made = await self.client.post(
            "/v1/agent-sessions",
            headers=created(person),
            json={"kind": "steward", "title": "t", "agent_project_id": AGENT_PROJECT_ID},
        )
        assert made.status_code == 201, made.text
        session_id = made.json()["id"]
        spoken = await self.client.post(
            f"/v1/agent-sessions/{session_id}/messages",
            headers=created(person),
            json={"text": "Count the dropped objects."},
        )
        assert spoken.status_code == 201, spoken.text
        return session_id

    async def run(self, session_id: str, by: Role = Role.MEMBER) -> Any:
        ctx = await self.ctx(self[by])
        return await self.container.managers.loop.run(ctx, UUID(session_id))

    async def parked_on(self, session_id: str) -> dict[str, Any]:
        """The park the session waits on, as the API reads it."""
        read = await self.client.get(f"/v1/agent-sessions/{session_id}", headers=self[Role.OWNER])
        assert read.status_code == 200, read.text
        assert read.json()["status"] == "parked", read.text
        return read.json()["park"]

    def runs_of(self, session_id: str) -> int:
        work = self.container.storage.get_work_storage()
        assert isinstance(work, WorkStorageMemoryImpl)
        items = [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]
        return len([i for i in items if i.kind == WorkKind.LOOP and str(i.target_id) == session_id])

    async def entries(self, kind: EntryKind) -> int:
        ledger = self.container.storage.get_spend_ledger_storage()
        return len(await ledger.read_entries(self.org_id, kind=kind, limit=50))

    async def runs_again(
        self, session_id: str, cleared: httpx.Response, runs: int, by: Role = Role.MEMBER
    ) -> None:
        """The route posted its entry, and the session is pending, its park
        gone, with one more run asked for; the next run goes on to the
        loop's end, and the model's last turn was read."""
        assert cleared.status_code == 201, cleared.text
        session = await self.client.get(
            f"/v1/agent-sessions/{session_id}", headers=self[Role.OWNER]
        )
        assert (session.json()["status"], session.json()["park"]) == ("pending", None)
        assert self.runs_of(session_id) == runs + 1, "the work that runs the session is queued"
        self.say(reply(said("Three dropped.")))
        run = await self.run(session_id, by)
        assert (run.end, run.outcome) == (RunEnd.ENDED, LoopOutcome.SUCCEEDED), run
        assert self.model.remaining == 0


@pytest.fixture
def providers() -> ModelProvidersInterface:
    return scripted_model_providers()


@pytest.fixture
def storage() -> StorageInterface:
    return StorageMemoryImpl()


@pytest.fixture
def pager() -> OperatorPagerMemoryImpl:
    return OperatorPagerMemoryImpl()


@pytest.fixture
def gate(storage: StorageInterface, pager: OperatorPagerMemoryImpl) -> MoneyGateImpl:
    return build_money_gate(
        storage, pager=pager, unit_plans=UNIT_PLANS_HERE, options=MoneyGateOptions(guard=GUARD)
    )


@pytest.fixture
def payments() -> PaymentProviderTwinImpl:
    return PaymentProviderTwinImpl()


@pytest.fixture
def container(
    tmp_path: Path,
    storage: StorageInterface,
    providers: ModelProvidersInterface,
    gate: MoneyGateImpl,
    payments: PaymentProviderTwinImpl,
) -> AppContainer:
    integrations = IntegrationsOverImpl(IdentityProviderAbsentImpl(), providers)
    ports = PlatformPorts(
        budget_gate=gate, kinds=ProductKinds(agents=(STEWARD,), tools=lambda _managers: ())
    )
    return build_container(tmp_path, storage, integrations, ports=ports, payments=payments)


@pytest.fixture
def case(
    client: httpx.AsyncClient,
    container: AppContainer,
    gate: MoneyGateImpl,
    pager: OperatorPagerMemoryImpl,
    payments: PaymentProviderTwinImpl,
    providers: ModelProvidersInterface,
) -> Case:
    return Case(client, container, gate, pager, payments, providers)


# A call far above its session's norm: a person who approves such calls.


async def test_a_call_far_above_its_norm_is_approved_by_a_person_who_approves_such_calls(
    case: Case,
) -> None:
    await case.seat("starter")
    session_id = await case.started()
    member = await case.ctx(case[Role.MEMBER])
    for _ in range(3):
        # The session's norm: three small calls, held and settled whole.
        request = HoldRequest(
            spender_id=member.user_id,
            scopes=(BudgetScope(kind=BudgetScopeKind.TENANT, key=str(case.org_id)),),
            exposure=Spend(cost_micros=1_000, tokens=0),
            session_id=UUID(session_id),
            purpose=MAIN,
        )
        hold = await case.gate.authorize_priced(member, request, None)
        assert isinstance(hold, FundedHold), hold
        await case.gate.settle(member, hold.id, Billed(usage=hold.hold.exposure))
    await case.run(session_id)
    assert (await case.parked_on(session_id))["unlock"] == ANOMALY_UNLOCK
    (page,) = case.pager.pages
    path = f"/v1/agent-sessions/{session_id}/cost-approval"
    body = {"up_to_micros": page.expected_micros}
    runs = case.runs_of(session_id)

    for refused in (Role.MEMBER, Role.VIEWER):
        answered = await case.client.post(path, headers=created(case[refused]), json=body)
        assert answered.status_code == 403, f"{refused}: {answered.text}"
    crossed = await case.client.post(path, headers=created(case.stranger), json=body)
    assert crossed.status_code == 404, crossed.text
    nothing = await case.client.post(
        path, headers=created(case[Role.ADMIN]), json={"up_to_micros": 0}
    )
    assert nothing.status_code == 422, nothing.text
    assert (await case.parked_on(session_id))["unlock"] == ANOMALY_UNLOCK
    assert await case.entries(EntryKind.APPROVAL) == 0, "nothing approved"

    approved = await case.client.post(path, headers=created(case[Role.ADMIN]), json=body)

    assert approved.json()["kind"] == "approval", approved.text
    assert approved.json()["amount_micros"] == page.expected_micros
    await case.runs_again(session_id, approved, runs)


# A budget a call passes: a person who sets budgets raises it for its window.


async def test_a_budget_a_call_passes_is_raised_for_its_window_by_a_person_who_sets_budgets(
    case: Case,
) -> None:
    await case.seat("starter")
    made = await case.client.post(
        "/v1/budgets",
        headers=created(case[Role.OWNER]),
        json={"scope_kind": "tenant", "window_kind": "day", "cost_micros": 1},
    )
    assert made.status_code == 201, made.text
    budget_id = made.json()["id"]
    session_id = await case.started()
    await case.run(session_id)
    assert (await case.parked_on(session_id))["unlock"] == budget_id
    path = f"/v1/budgets/{budget_id}/raises"
    body = {"cost_micros": PLENTY}
    runs = case.runs_of(session_id)

    for refused in (Role.MEMBER, Role.VIEWER):
        answered = await case.client.post(path, headers=created(case[refused]), json=body)
        assert answered.status_code == 403, f"{refused}: {answered.text}"
    crossed = await case.client.post(path, headers=created(case.stranger), json=body)
    assert crossed.status_code == 404, crossed.text
    empty = await case.client.post(path, headers=created(case[Role.ADMIN]), json={})
    assert empty.status_code == 422, empty.text
    assert (await case.parked_on(session_id))["unlock"] == budget_id
    assert await case.entries(EntryKind.RAISE) == 0, "nothing raised"

    keyed = created(case[Role.ADMIN])
    raised = await case.client.post(path, headers=keyed, json=body)
    again = await case.client.post(path, headers=keyed, json=body)

    assert raised.json()["kind"] == "raise", raised.text
    assert (raised.json()["budget_id"], raised.json()["cost_micros"]) == (budget_id, PLENTY)
    assert again.headers.get("Idempotent-Replayed") == "true", "a retry posts once"
    assert again.json() == raised.json()
    assert await case.entries(EntryKind.RAISE) == 1
    budget = await case.client.get(f"/v1/budgets/{budget_id}", headers=case[Role.OWNER])
    assert budget.json()["cost_micros"] == 1, "the budget's own amount is unchanged"
    await case.runs_again(session_id, raised, runs)


# Funds that cover no call: a payment the provider confirmed, or a grant.


async def test_funds_that_cover_no_call_are_topped_up_by_a_payment_the_provider_confirmed(
    case: Case,
) -> None:
    await case.seat("prepaid")
    session_id = await case.started()
    await case.run(session_id)
    park = await case.parked_on(session_id)
    assert (park["unlock"], park["retry_at"]) == (FUNDS_UNLOCK, None)
    path = "/v1/agent-billing/payments"
    payload, signature = case.payments.confirm(case.org_id, PLENTY, utcnow())
    signed = {"Payment-Signature": signature}
    runs = case.runs_of(session_id)

    viewer = await case.client.post(path, headers={**case[Role.VIEWER], **signed}, content=payload)
    assert viewer.status_code == 403, viewer.text
    forged = await case.client.post(
        path, headers={**case[Role.MEMBER], "Payment-Signature": "t=1, v1=00"}, content=payload
    )
    assert forged.status_code == 400, forged.text
    unsigned = await case.client.post(path, headers=case[Role.MEMBER], content=payload)
    assert unsigned.status_code == 400, unsigned.text
    theirs = await case.client.post(path, headers={**case.stranger, **signed}, content=payload)
    assert theirs.status_code == 403, "a confirmation of another tenant credits nobody"
    assert (await case.parked_on(session_id))["unlock"] == FUNDS_UNLOCK
    assert await case.entries(EntryKind.CREDIT) == 0, "nothing credited"

    paid = await case.client.post(path, headers={**case[Role.MEMBER], **signed}, content=payload)
    again = await case.client.post(path, headers={**case[Role.MEMBER], **signed}, content=payload)

    assert paid.json()["kind"] == "credit", paid.text
    assert paid.json()["amount_micros"] == PLENTY
    assert again.json()["id"] == paid.json()["id"], "one payment credits once"
    assert await case.entries(EntryKind.CREDIT) == 1
    await case.runs_again(session_id, paid, runs)


async def test_a_payment_wakes_the_sessions_on_the_funds_the_payer_does_not_see_too(
    case: Case,
) -> None:
    await case.seat("prepaid")
    theirs = await case.started(by=Role.OWNER)
    hidden = await case.client.put(
        f"/v1/agent-sessions/{theirs}/visibility",
        headers=case[Role.OWNER],
        json={"visibility": "private"},
    )
    assert hidden.status_code == 200, hidden.text
    mine = await case.started()
    await case.run(theirs, by=Role.OWNER)
    await case.run(mine)
    for session_id in (theirs, mine):
        assert (await case.parked_on(session_id))["unlock"] == FUNDS_UNLOCK
    unseen = await case.client.get(f"/v1/agent-sessions/{theirs}", headers=case[Role.MEMBER])
    assert unseen.status_code == 404, "the payer does not see the owner's private session"
    payload, signature = case.payments.confirm(case.org_id, PLENTY, utcnow())
    runs = {session_id: case.runs_of(session_id) for session_id in (theirs, mine)}

    paid = await case.client.post(
        "/v1/agent-billing/payments",
        headers={**created(case[Role.MEMBER]), "Payment-Signature": signature},
        content=payload,
    )

    assert paid.json()["kind"] == "credit", paid.text
    await case.runs_again(theirs, paid, runs[theirs], by=Role.OWNER)
    await case.runs_again(mine, paid, runs[mine])


async def test_funds_that_cover_no_call_are_granted_by_an_operator_who_may_write(
    case: Case,
) -> None:
    await case.seat("prepaid")
    session_id = await case.started()
    await case.run(session_id)
    assert (await case.parked_on(session_id))["unlock"] == FUNDS_UNLOCK
    reader, _ = await enrol_operator(
        case.client, case.container, "sup@example.test", OperatorRole.READ
    )
    writer, _ = await enrol_operator(
        case.client, case.container, "ops@example.test", OperatorRole.WRITE
    )
    path = f"/v1/admin/orgs/{case.org_id}/grants"
    body = {"units": PLENTY, "reason": "a pilot's first month"}
    runs = case.runs_of(session_id)

    for refused in (case[Role.OWNER], reader):
        answered = await case.client.post(path, headers=created(refused), json=body)
        assert answered.status_code in (401, 403), answered.text
    gone = await case.client.post(
        f"/v1/admin/orgs/{new_id()}/grants", headers=created(writer), json=body
    )
    assert gone.status_code == 404, gone.text
    assert (await case.parked_on(session_id))["unlock"] == FUNDS_UNLOCK
    assert await case.entries(EntryKind.GRANT) == 0, "nothing granted"

    keyed = created(writer)
    granted = await case.client.post(path, headers=keyed, json=body)
    again = await case.client.post(path, headers=keyed, json=body)

    assert granted.json()["kind"] == "grant", granted.text
    assert (granted.json()["units"], granted.json()["reason"]) == (PLENTY, body["reason"])
    assert again.headers.get("Idempotent-Replayed") == "true", "a retry grants once"
    assert await case.entries(EntryKind.GRANT) == 1
    await case.runs_again(session_id, granted, runs)
