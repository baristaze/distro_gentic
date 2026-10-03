"""Each link a park's notification carries, followed over the live app: the
route answers for whoever can clear the park, and refuses anyone else, a
member whose role cannot clear it and another tenant's person alike. And
the person's own list: they read what waits on them and mark it read, and
nobody reads or marks another's."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, add_member, build_container, seed_request, sign_in_as
from contracts.step_storage import make_message, make_request, make_response, make_tool_request

from acme.om.agent_sessions.rules import QUESTION
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.budgets.types.budget import Budget, BudgetScopeKind, WindowKind
from acme.om.context import Role, TenantContext
from acme.om.intake.root import build_intake
from acme.om.notifications.root import build_notifications
from acme.om.notifications.types.notification import PORTAL, Notification
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import Step
from acme.services.api.container import AppContainer
from acme.services.api.seed import first_project

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


class Tenant:
    """One tenant, with a person in each role signed in, and another
    tenant's owner."""

    def __init__(self, org_id: UUID, headers: dict[Role, dict[str, str]]) -> None:
        self.org_id = org_id
        self.headers = headers
        self.stranger: dict[str, str] = {}

    def __getitem__(self, role: Role) -> dict[str, str]:
        return self.headers[role]


@pytest.fixture
async def ajax(client: httpx.AsyncClient, container: AppContainer) -> Tenant:
    ctx, org = await container.managers.tenancy.bootstrap(
        seed_request(), "Ajax", "ajax", "owner@ajax.test", "Owner"
    )
    project = first_project(ctx).model_copy(update={"id": UUID(PROJECT_ID)})
    await container.storage.get_project_storage().create_project(org.id, project, ())
    headers = {Role.OWNER: await sign_in_as(client, "owner@ajax.test", org.id)}
    for role in (Role.ADMIN, Role.MEMBER, Role.VIEWER):
        email = f"{role.value}@ajax.test"
        await add_member(container, org.id, email, role)
        headers[role] = await sign_in_as(client, email, org.id)
    tenant = Tenant(org.id, headers)
    _, other = await container.managers.tenancy.bootstrap(
        seed_request(), "Bravo", "bravo", "owner@bravo.test", "Owner"
    )
    tenant.stranger = await sign_in_as(client, "owner@bravo.test", other.id)
    return tenant


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


async def context_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def parked(
    client: httpx.AsyncClient,
    container: AppContainer,
    tenant: Tenant,
    park: Park,
    *,
    call: bool = False,
) -> LoopRun:
    """A session the member asked for, whose run parked on `park`, as the
    loop parks one; with `call`, after a tool call it holds."""
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(tenant[Role.MEMBER]),
        json={"kind": "assistant", "title": "the dropped object", "project_id": PROJECT_ID},
    )
    assert started.status_code == 201, started.text
    session_id = UUID(started.json()["id"])
    ctx = await context_of(container, tenant[Role.MEMBER])
    sessions, steps = container.managers.agent_sessions, container.managers.steps
    member = Principal(kind=PrincipalKind.PERSON, id=ctx.user_id)
    (message,) = await steps.append_inputs(
        ctx, session_id, [make_message(session_id, principal=member)]
    )
    epoch = await steps.begin_run(ctx, session_id)
    written: list[Step] = []
    if call:
        request = make_request(session_id, message.id, (message.id,))
        response = make_response(session_id, message.id, request.id)
        written = [request, response, make_tool_request(session_id, message.id, response.id)]
        await steps.append_steps(ctx, session_id, epoch, written)
    await sessions.park(ctx, session_id, epoch, message.id, park)
    return LoopRun(
        session_id=session_id, epoch=epoch, loop_id=message.id, end=RunEnd.PARKED, park=park
    )


async def told(container: AppContainer, tenant: Tenant, run: LoopRun) -> list[Notification]:
    """What the park tells, on the platform's own list, as the runner tells
    it after the run."""
    intake = build_intake(container.storage, container.managers)
    notifications = build_notifications(
        container.storage, container.managers, container.integrations, intake
    )
    service = await container.managers.tenancy.service_context(
        seed_request(), tenant.org_id, EMPTY_UUID
    )
    found = await notifications.notify_park(service, run)
    return [n for n in found if n.channel == PORTAL]


async def recipients(
    container: AppContainer, tenant: Tenant, told_: list[Notification]
) -> set[Role]:
    users = {
        (await context_of(container, headers)).user_id: role
        for role, headers in tenant.headers.items()
    }
    return {users[n.recipient] for n in told_}


async def follow(
    client: httpx.AsyncClient, method: str, link: str, headers: dict[str, str], **extra: Any
) -> httpx.Response:
    return await client.request(method, link, headers=created(headers), **extra)


async def test_a_held_calls_link_answers_its_approvers_alone(
    client: httpx.AsyncClient, container: AppContainer, ajax: Tenant
) -> None:
    run = await parked(
        client, container, ajax, Park(reason=ParkReason.PERSON, unlock=APPROVAL_UNLOCK), call=True
    )
    notified = await told(container, ajax, run)
    assert await recipients(container, ajax, notified) == {Role.OWNER, Role.ADMIN}
    (link,) = {n.link for n in notified}
    decision = {"json": {"approve": True}}
    for refused, status in ((Role.MEMBER, 403), (Role.VIEWER, 403)):
        answered = await follow(client, "POST", link, ajax[refused], **decision)
        assert answered.status_code == status, f"{refused}: {answered.text}"
    crossed = await follow(client, "POST", link, ajax.stranger, **decision)
    assert crossed.status_code == 404, crossed.text
    approved = await follow(client, "POST", link, ajax[Role.ADMIN], **decision)
    assert approved.status_code == 201, approved.text


async def test_a_park_on_its_requesters_link_answers_who_may_steer_it_alone(
    client: httpx.AsyncClient, container: AppContainer, ajax: Tenant
) -> None:
    run = await parked(client, container, ajax, Park(reason=ParkReason.PERSON, unlock="deadline"))
    notified = await told(container, ajax, run)
    assert await recipients(container, ajax, notified) == {Role.MEMBER}
    (link,) = {n.link for n in notified}
    unlock = {"json": {"command": "unlock"}}
    viewer = await follow(client, "POST", link, ajax[Role.VIEWER], **unlock)
    assert viewer.status_code == 403, viewer.text
    crossed = await follow(client, "POST", link, ajax.stranger, **unlock)
    assert crossed.status_code == 404, crossed.text
    answered = await follow(client, "POST", link, ajax[Role.MEMBER], **unlock)
    assert answered.status_code == 201, answered.text


async def test_a_questions_link_takes_its_requesters_answer_as_a_message(
    client: httpx.AsyncClient, container: AppContainer, ajax: Tenant
) -> None:
    run = await parked(client, container, ajax, QUESTION)
    notified = await told(container, ajax, run)
    assert await recipients(container, ajax, notified) == {Role.MEMBER}
    (link,) = {n.link for n in notified}
    assert link == f"/v1/agent-sessions/{run.session_id}/messages"
    answer = {"json": {"text": "Week 12."}}
    viewer = await follow(client, "POST", link, ajax[Role.VIEWER], **answer)
    assert viewer.status_code == 403, viewer.text
    crossed = await follow(client, "POST", link, ajax.stranger, **answer)
    assert crossed.status_code == 404, crossed.text
    path = f"/v1/agent-sessions/{run.session_id}"
    assert (await client.get(path, headers=ajax[Role.MEMBER])).json()["park"] is not None
    answered = await follow(client, "POST", link, ajax[Role.MEMBER], **answer)
    assert answered.status_code == 201, answered.text
    session = await client.get(path, headers=ajax[Role.MEMBER])
    assert session.json()["park"] is None, "the answer clears the park"


async def test_a_budgets_link_answers_who_sets_budgets_alone(
    client: httpx.AsyncClient, container: AppContainer, ajax: Tenant
) -> None:
    owner = await context_of(container, ajax[Role.OWNER])
    now = utcnow()
    budget = await container.managers.budgets.create_budget(
        owner,
        Budget(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=owner.user_id,
            updated_by=owner.user_id,
            scope_kind=BudgetScopeKind.TENANT,
            scope_key=str(ajax.org_id),
            window_kind=WindowKind.LIFE,
            cost_micros=1,
        ),
    )
    run = await parked(
        client, container, ajax, Park(reason=ParkReason.BUDGET, unlock=str(budget.id))
    )
    notified = await told(container, ajax, run)
    assert await recipients(container, ajax, notified) == {Role.OWNER, Role.ADMIN}
    (link,) = {n.link for n in notified}
    assert link == f"/v1/budgets/{budget.id}/amount"
    raised = {"json": {"cost_micros": 5_000_000}}
    for refused in (Role.MEMBER, Role.VIEWER):
        answered = await follow(client, "PUT", link, {**ajax[refused], "If-Match": '"1"'}, **raised)
        assert answered.status_code == 403, f"{refused}: {answered.text}"
    crossed = await follow(client, "PUT", link, {**ajax.stranger, "If-Match": '"1"'}, **raised)
    assert crossed.status_code == 404, crossed.text
    unread = await follow(client, "PUT", link, ajax[Role.ADMIN], **raised)
    assert unread.status_code == 422, "a change names the version it read"
    answered = await follow(client, "PUT", link, {**ajax[Role.ADMIN], "If-Match": '"1"'}, **raised)
    assert answered.status_code == 200, answered.text
    assert (answered.json()["cost_micros"], answered.json()["version"]) == (5_000_000, 2)
    stale = await follow(client, "PUT", link, {**ajax[Role.OWNER], "If-Match": '"1"'}, **raised)
    assert stale.status_code == 412, stale.text


async def test_the_automation_principals_grant_answers_who_manages_members_alone(
    client: httpx.AsyncClient, ajax: Tenant
) -> None:
    grant = {"json": {"role": "member"}}
    for refused in (Role.MEMBER, Role.VIEWER):
        answered = await follow(client, "PUT", "/v1/automations/principal", ajax[refused], **grant)
        assert answered.status_code == 403, f"{refused}: {answered.text}"
    above = await follow(
        client, "PUT", "/v1/automations/principal", ajax[Role.ADMIN], json={"role": "owner"}
    )
    assert above.status_code == 403, above.text
    granted = await follow(client, "PUT", "/v1/automations/principal", ajax[Role.ADMIN], **grant)
    assert granted.status_code == 200, granted.text
    read = await client.get("/v1/automations/principal", headers=ajax[Role.VIEWER])
    assert read.json()["id"] == granted.json()["id"]
    elsewhere = await client.get("/v1/automations/principal", headers=ajax.stranger)
    assert elsewhere.status_code == 404, elsewhere.text


async def test_a_person_reads_and_marks_their_own_notifications_alone(
    client: httpx.AsyncClient, container: AppContainer, ajax: Tenant
) -> None:
    run = await parked(client, container, ajax, Park(reason=ParkReason.PERSON, unlock="deadline"))
    (mine,) = await told(container, ajax, run)
    listed = await client.get("/v1/notifications", headers=ajax[Role.MEMBER])
    assert [n["id"] for n in listed.json()] == [str(mine.id)]
    assert listed.json()[0]["read_at"] is None
    for other in (ajax[Role.OWNER], ajax.stranger):
        assert (await client.get("/v1/notifications", headers=other)).json() == []
        crossed = await client.post(f"/v1/notifications/{mine.id}/read", headers=other)
        assert crossed.status_code == 404, crossed.text
    marked = await client.post(f"/v1/notifications/{mine.id}/read", headers=ajax[Role.MEMBER])
    assert marked.status_code == 200, marked.text
    again = await client.post(f"/v1/notifications/{mine.id}/read", headers=ajax[Role.MEMBER])
    assert marked.json()["read_at"] is not None
    assert again.json()["read_at"] == marked.json()["read_at"]
