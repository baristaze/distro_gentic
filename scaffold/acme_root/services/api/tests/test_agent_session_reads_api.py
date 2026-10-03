"""A session's reads over the live app, in memory: the tenant's sessions
listed in a status a page at a time, a session's children, archive, delete
and restore, each by the role that may; what a session asks of a person
and the calls it holds, per session and across the tenant; its bounds, its
tool calls, and its usage, and the tenant's usage across its budgets; the
runs and validations a session's evidence holds, and what it delivered;
and every route that names a session, called by another tenant with one
that exists, answered as an unknown id is. No runner works behind the API
here, so a case writes a loop's steps, its runs, and its bound work
itself, the way a run writes them."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, add_member, build_container, seed_request, sign_in_as
from contracts.agent_session_storage import make_session
from contracts.evidence_storage import make_record, make_validation
from contracts.intake_storage import make_binding
from contracts.ledger_storage import a_hold
from contracts.step_storage import (
    make_request,
    make_response,
    make_tool_request,
    make_tool_response,
)

from acme.integrations.model_providers.types import Usage
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.budgets.rules import window_bounds
from acme.om.budgets.types.amount import Amount
from acme.om.budgets.types.budget import Budget, BudgetScopeKind, WindowKind
from acme.om.budgets.types.hold import HoldLine
from acme.om.context import Role, TenantContext
from acme.om.intake.types.link import HandleKind
from acme.om.steps.types.header import (
    AcceptedResult,
    ControlCommand,
    ControlHeader,
    DecidedCall,
    LoopOutcome,
    ModelResponseHeader,
    Park,
    ParkReason,
    ToolRequestHeader,
    ToolResponseHeader,
)
from acme.om.steps.types.step import Actor, Origin, Step, StepType
from acme.services.api.container import AppContainer
from acme.services.api.services.impl.session_reads import tool_calls_of

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=2, count=4),
)


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test container with one kind the product runs."""
    return build_container(tmp_path, agent_kinds=(ASSISTANT,))


def created(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


async def start(client: httpx.AsyncClient, headers: dict[str, str], title: str) -> dict[str, Any]:
    answered = await client.post(
        "/v1/agent-sessions",
        headers=created(headers),
        json={"kind": "assistant", "title": title, "project_id": PROJECT_ID},
    )
    assert answered.status_code == 201, answered.text
    return answered.json()


async def context_of(container: AppContainer, headers: dict[str, str]) -> TenantContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def spawn(container: AppContainer, headers: dict[str, str], parent_id: str) -> str:
    """A sub-agent of the session, as the loop's spawn writes it."""
    ctx = await context_of(container, headers)
    sessions = container.managers.agent_sessions
    parent = await sessions.get_session(ctx, UUID(parent_id))
    child = await sessions.create_session(ctx, make_session(parent=parent))
    return str(child.id)


def used(response: Step, usage: Usage) -> Step:
    header = response.header
    assert isinstance(header, ModelResponseHeader)
    return response.model_copy(update={"header": header.model_copy(update={"usage": usage})})


async def a_loop(
    client: httpx.AsyncClient,
    container: AppContainer,
    headers: dict[str, str],
    *,
    calls: int,
    answered: int = 0,
    park: Park | None = None,
    accepted: AcceptedResult | None = None,
) -> dict[str, Any]:
    """A session a person spoke to, whose loop made one model call that
    asked for `calls` tool calls, the first `answered` of them answered,
    the last of those with `accepted` as its verdict when one is named,
    and then parked on `park`, when one is named."""
    session = await start(client, headers, "the dropped object")
    said = await client.post(
        f"/v1/agent-sessions/{session['id']}/messages",
        headers=created(headers),
        json={"text": "go"},
    )
    assert said.status_code == 201, said.text
    ctx = await context_of(container, headers)
    managers = container.managers
    sid, loop_id = UUID(session["id"]), UUID(said.json()["loop_id"])
    request = make_request(sid, loop_id, (UUID(said.json()["id"]),))
    response = used(make_response(sid, loop_id, request.id), Usage(input=100, output=20))
    steps: list[Step] = [request, response]
    for index in range(calls):
        call = make_tool_request(sid, loop_id, response.id)
        steps.append(call)
        if index < answered:
            answer = make_tool_response(sid, loop_id, call.id)
            if accepted is not None and index == answered - 1:
                answer = answer.model_copy(update={"header": ToolResponseHeader(accepted=accepted)})
            steps.append(answer)
    epoch = await managers.steps.begin_run(ctx, sid)
    await managers.steps.append_steps(ctx, sid, epoch, steps)
    if park is not None:
        await managers.agent_sessions.park(ctx, sid, epoch, loop_id, park)
    return session


APPROVAL = Park(reason=ParkReason.PERSON, unlock="approval")
STEP_GUARD = Park(reason=ParkReason.PERSON, unlock="step_guard")


async def viewer_of(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> dict[str, str]:
    me = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(me.json()["id"])
    await add_member(container, org_id, "vic@example.test", Role.VIEWER)
    return await sign_in_as(client, "vic@example.test", org_id)


async def test_a_member_lists_the_tenants_sessions_in_a_status_a_page_at_a_time(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    started = [await start(client, owner, f"session {index}") for index in range(3)]
    woken = started[1]["id"]
    said = await client.post(
        f"/v1/agent-sessions/{woken}/messages", headers=created(owner), json={"text": "go"}
    )
    assert said.status_code == 201, said.text

    first = await client.get("/v1/agent-sessions", headers=owner, params={"limit": 2})
    second = await client.get(
        "/v1/agent-sessions",
        headers=owner,
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )
    pending = await client.get("/v1/agent-sessions", headers=owner, params={"status": "pending"})
    idle = await client.get("/v1/agent-sessions", headers=owner, params={"status": "idle"})

    assert first.status_code == 200, first.text
    paged = [s["id"] for s in first.json()["items"] + second.json()["items"]]
    assert paged == sorted(s["id"] for s in started)
    assert second.json()["next_cursor"] is None
    assert [s["id"] for s in pending.json()["items"]] == [woken]
    assert {s["id"] for s in idle.json()["items"]} == {started[0]["id"], started[2]["id"]}


async def test_a_cursor_of_another_list_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    for index in range(2):
        await start(client, owner, f"session {index}")
    files = await client.get("/v1/api-keys", headers=owner, params={"limit": 1})
    stolen = files.json()["next_cursor"] or "bm90IGEgY3Vyc29y"

    refused = await client.get("/v1/agent-sessions", headers=owner, params={"cursor": stolen})

    assert refused.status_code == 422, refused.text


async def test_a_sessions_children_are_listed_with_their_parent(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    parent = await start(client, owner, "the parent")
    children = sorted([await spawn(container, owner, parent["id"]) for _ in range(3)])

    first = await client.get(
        f"/v1/agent-sessions/{parent['id']}/children", headers=owner, params={"limit": 2}
    )
    rest = await client.get(
        f"/v1/agent-sessions/{parent['id']}/children",
        headers=owner,
        params={"cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200, first.text
    items = first.json()["items"] + rest.json()["items"]
    assert [child["id"] for child in items] == children
    assert {(c["parent_id"], c["root_id"]) for c in items} == {(parent["id"], parent["id"])}
    assert rest.json()["next_cursor"] is None


async def test_a_member_archives_deletes_and_restores_a_session_and_a_viewer_does_not(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await start(client, owner, "the dropped object")
    path = f"/v1/agent-sessions/{session['id']}"
    viewer = await viewer_of(client, container, owner)

    refused = [
        (await client.post(f"{path}/archive", headers=viewer)).status_code,
        (await client.delete(path, headers=viewer)).status_code,
    ]
    archived = await client.post(f"{path}/archive", headers=owner)
    deleted = await client.delete(path, headers=owner)
    hidden = await client.get(path, headers=owner)
    listed = await client.get("/v1/agent-sessions", headers=owner)
    not_restored = await client.post(f"{path}/restore", headers=viewer)
    restored = await client.post(f"{path}/restore", headers=owner)
    back = await client.get(path, headers=owner)

    assert refused == [403, 403]
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None
    assert hidden.status_code == 404 and listed.json()["items"] == []
    assert not_restored.status_code == 403
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert back.status_code == 200 and back.json()["archived_at"] is not None


async def test_a_session_with_a_loop_open_is_neither_archived_nor_deleted(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner, "the dropped object")
    path = f"/v1/agent-sessions/{session['id']}"
    said = await client.post(f"{path}/messages", headers=created(owner), json={"text": "go"})
    assert said.status_code == 201, said.text

    archived = await client.post(f"{path}/archive", headers=owner)
    deleted = await client.delete(path, headers=owner)

    assert (archived.status_code, deleted.status_code) == (422, 422)


async def test_what_a_session_waits_on_a_person_for_is_read_per_session_and_across_the_tenant(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    holding = await a_loop(client, container, owner, calls=2, park=APPROVAL)
    asking = await a_loop(client, container, owner, calls=0, park=STEP_GUARD)
    held_at = f"/v1/agent-sessions/{holding['id']}"
    asked_at = f"/v1/agent-sessions/{asking['id']}"

    approvals = await client.get(f"{held_at}/approvals", headers=owner)
    none_asked = await client.get(f"{held_at}/questions", headers=owner)
    questions = await client.get(f"{asked_at}/questions", headers=owner)
    none_held = await client.get(f"{asked_at}/approvals", headers=owner)
    first = await client.get("/v1/approvals", headers=owner, params={"limit": 1})
    rest = await client.get(
        "/v1/approvals", headers=owner, params={"cursor": first.json()["next_cursor"]}
    )

    assert approvals.status_code == 200, approvals.text
    assert [(a["seq"], a["tool"], a["authorization_class"]) for a in approvals.json()] == [
        (4, "read_log", "read"),
        (5, "read_log", "read"),
    ]
    assert none_asked.json() == [] and none_held.json() == []
    assert questions.status_code == 200, questions.text
    assert [(q["seq"], q["unlock"]) for q in questions.json()] == [(4, "step_guard")]
    assert first.status_code == 200, first.text
    across = first.json()["items"] + rest.json()["items"]
    assert sorted((a["session_id"], a["seq"]) for a in across) == [
        (holding["id"], 4),
        (holding["id"], 5),
    ]
    assert rest.json()["next_cursor"] is None


async def test_a_sessions_tool_calls_carry_their_decision_and_answer_and_its_usage_sums(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await a_loop(client, container, owner, calls=2, answered=1, park=APPROVAL)
    path = f"/v1/agent-sessions/{session['id']}"
    decided = await client.post(
        f"{path}/calls/6/decision", headers=created(owner), json={"approve": True}
    )
    assert decided.status_code == 201, decided.text
    me = await client.get("/v1/me", headers=owner)

    calls = await client.get(f"{path}/tool-calls", headers=owner)
    after = await client.get(f"{path}/tool-calls", headers=owner, params={"after_seq": 4})
    usage = await client.get(f"{path}/usage", headers=owner)

    assert calls.status_code == 200, calls.text
    items = calls.json()["items"]
    assert [(c["seq"], c["response_seq"], c["decision"]) for c in items] == [
        (4, 5, None),
        (6, None, "approved"),
    ]
    assert items[1]["decided_by"] == me.json()["user"]["id"]
    assert [c["seq"] for c in after.json()["items"]] == [6]
    assert usage.status_code == 200, usage.text
    assert (usage.json()["calls"], usage.json()["input"], usage.json()["output"]) == (1, 100, 20)
    assert [f["fill"] for f in usage.json()["fills"]] == ["anthropic/claude-sonnet-5-5"]


def test_an_approved_call_that_ran_stays_approved_once_its_approval_lapses() -> None:
    """A decision reads as of the call's response: the approval let the
    call run, and its lifetime passing later changes nothing."""
    sid, loop_id = new_id(), new_id()
    request = make_request(sid, loop_id, (new_id(),))
    response = make_response(sid, loop_id, request.id)
    call = make_tool_request(sid, loop_id, response.id)
    header = call.header
    assert isinstance(header, ToolRequestHeader)
    now = utcnow()
    decision = Step(
        id=new_id(),
        created_at=now,
        session_id=sid,
        loop_id=loop_id,
        type=StepType.CONTROL,
        actor=Actor.PERSON,
        origin=Origin.API,
        refs=(call.id,),
        header=ControlHeader(
            command=ControlCommand.APPROVE,
            call=DecidedCall(
                tool=header.tool,
                input_hash=header.input_hash,
                decided_by=uuid4(),
                role=Role.MEMBER,
                expires_at=now + timedelta(hours=1),
            ),
        ),
    )
    ran = make_tool_response(sid, loop_id, call.id)
    history = [request, response, call, decision, ran]

    (soon,) = tool_calls_of(history, now + timedelta(seconds=1))
    (later,) = tool_calls_of(history, now + timedelta(hours=2))
    (waiting,) = tool_calls_of(history[:-1], now + timedelta(hours=2))

    assert (soon.decision, later.decision) == ("approved", "approved")
    assert waiting.decision == "expired", "a call that never ran outlives its approval"


async def test_a_sessions_bounds_are_its_kinds_loop_limits_and_its_trees(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner, "the dropped object")

    bounds = await client.get(f"/v1/agent-sessions/{session['id']}/bounds", headers=owner)

    assert bounds.status_code == 200, bounds.text
    body = bounds.json()
    assert (body["kind"], body["kind_version"]) == ("assistant", 1)
    assert body["loop"]["step_guard"] == 50 and body["loop"]["run_time_seconds"] == 900
    tree = body["tree"]
    assert (tree["root_id"], tree["height"], tree["count"], tree["size"]) == (
        session["id"],
        2,
        4,
        0,
    )


async def test_a_sessions_runs_and_validations_are_read_oldest_first_a_page_at_a_time(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await start(client, owner, "the dropped object")
    path = f"/v1/agent-sessions/{session['id']}"
    ctx = await context_of(container, owner)
    sid = UUID(session["id"])
    runs = [make_record(sid, check=f"unit-{index}") for index in range(3)]
    for record in runs:
        await container.managers.evidence.record_run(ctx, record)
    validation, validated = make_validation(sid, 2)
    evidence = container.storage.get_evidence_storage()
    await evidence.create_validation(ctx.org_id, validation, validated)

    whole = await client.get(f"{path}/executions", headers=owner)
    first = await client.get(f"{path}/executions", headers=owner, params={"limit": 2})
    rest = await client.get(
        f"{path}/executions", headers=owner, params={"cursor": first.json()["next_cursor"]}
    )
    validations = await client.get(f"{path}/validations", headers=owner)

    assert whole.status_code == 200, whole.text
    every = [run["id"] for run in whole.json()["items"]]
    assert set(every) == {str(record.id) for record in (*runs, *validated)}
    assert [run["id"] for run in first.json()["items"] + rest.json()["items"]] == every
    assert rest.json()["next_cursor"] is None
    work = next(run for run in whole.json()["items"] if run["id"] == str(runs[0].id))
    assert (work["purpose"], work["check"], work["outcome"]) == ("work", "unit-0", "passed")
    assert work["cases"] == {"passed": 1, "failed": 0, "skipped": 0}
    assert validations.status_code == 200, validations.text
    assert [(v["id"], v["records"]) for v in validations.json()] == [
        (str(validation.id), [str(record.id) for record in validated])
    ]


async def test_a_sessions_delivery_is_its_branch_its_bound_work_and_its_accepted_result(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    done = AcceptedResult(outcome=LoopOutcome.SUCCEEDED, verified=True)
    session = await a_loop(client, container, owner, calls=1, answered=1, accepted=done)
    path = f"/v1/agent-sessions/{session['id']}"
    ctx = await context_of(container, owner)
    sid = UUID(session["id"])
    workspace = await container.managers.workspaces.get_workspace(ctx, sid)
    intake = container.storage.get_intake_storage()
    await intake.create_binding(ctx.org_id, make_binding("acme/checkout#12", sid))
    untouched = await start(client, owner, "nothing yet")

    delivery = await client.get(f"{path}/delivery", headers=owner)
    nothing = await client.get(f"/v1/agent-sessions/{untouched['id']}/delivery", headers=owner)

    assert delivery.status_code == 200, delivery.text
    body = delivery.json()
    assert (body["branch"], body["branch_seen"]) == (workspace.branch, False)
    assert [(w["kind"], w["handle"]) for w in body["work"]] == [
        (HandleKind.PULL_REQUEST.value, "acme/checkout#12")
    ]
    assert body["report"]["seq"] == 5
    assert (body["report"]["outcome"], body["report"]["verified"]) == ("succeeded", True)
    assert nothing.status_code == 200, nothing.text
    assert (nothing.json()["work"], nothing.json()["report"]) == ([], None)


async def test_the_tenants_usage_is_each_budget_with_what_its_window_spent(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    ctx = await context_of(container, owner)
    now = utcnow()
    budgets = [
        await container.managers.budgets.create_budget(
            ctx,
            Budget(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                scope_kind=BudgetScopeKind.TENANT,
                scope_key=f"{ctx.org_id}-{index}",
                window_kind=WindowKind.LIFE,
                cost_micros=1_000_000,
            ),
        )
        for index in range(2)
    ]
    charged = budgets[0]
    start_at, resets_at = window_bounds(charged.window, now)
    line = HoldLine(
        budget_id=charged.id,
        scope=charged.scope,
        window_start=start_at,
        resets_at=resets_at,
        amount=Amount(cost_micros=1_000_000),
    )
    ledger = container.storage.get_ledger_storage()
    assert await ledger.open_hold(ctx.org_id, a_hold(line, cost_micros=600, tokens=100)) is None

    first = await client.get("/v1/usage", headers=owner, params={"limit": 1})
    rest = await client.get(
        "/v1/usage", headers=owner, params={"cursor": first.json()["next_cursor"]}
    )

    assert first.status_code == 200, first.text
    items = first.json()["items"] + rest.json()["items"]
    assert sorted(item["budget"]["id"] for item in items) == sorted(str(b.id) for b in budgets)
    held = {item["budget"]["id"]: item["held_cost_micros"] for item in items}
    assert held == {str(budgets[0].id): 600, str(budgets[1].id): 0}
    assert {item["spent_cost_micros"] for item in items} == {0}
    assert rest.json()["next_cursor"] is None


async def test_every_read_reaches_a_viewer_and_no_route_reaches_another_tenants_session(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """Every route this file reads or writes a session by, called by another
    tenant with a session that exists: each is the 404 an unknown id gets.
    The tenant-wide lists another tenant reads carry none of it. A viewer
    reads every one."""
    session = await a_loop(client, container, owner, calls=1, park=APPROVAL)
    path = f"/v1/agent-sessions/{session['id']}"
    viewer = await viewer_of(client, container, owner)
    _, other = await container.managers.tenancy.bootstrap(
        seed_request(), "Other", "other", "owner@other.test", "Other"
    )
    stranger = await sign_in_as(client, "owner@other.test", other.id)
    unknown = f"/v1/agent-sessions/{UUID(int=7)}"
    reads = [
        "/children",
        "/questions",
        "/approvals",
        "/bounds",
        "/tool-calls",
        "/usage",
        "/executions",
        "/validations",
        "/delivery",
    ]
    writes = [("POST", "/archive"), ("POST", "/restore"), ("DELETE", "")]

    for method, tail in [("GET", tail) for tail in reads] + writes:
        crossed = await client.request(method, f"{path}{tail}", headers=stranger)
        missing = await client.request(method, f"{unknown}{tail}", headers=stranger)
        assert crossed.status_code == 404, f"{method} {tail}: {crossed.text}"
        assert (crossed.status_code, crossed.json()["error"]["code"]) == (
            missing.status_code,
            missing.json()["error"]["code"],
        ), f"{method} {tail}"
    for tail in reads:
        read = await client.get(f"{path}{tail}", headers=viewer)
        assert read.status_code == 200, f"GET {tail}: {read.text}"
    for listed in ("/v1/agent-sessions", "/v1/approvals", "/v1/usage"):
        theirs = await client.get(listed, headers=stranger)
        assert theirs.status_code == 200, f"{listed}: {theirs.text}"
        assert session["id"] not in theirs.text, listed
    still = await client.get(path, headers=owner)
    assert (still.json()["archived_at"], still.json()["deleted_at"]) == (None, None)
