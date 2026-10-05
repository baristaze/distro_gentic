"""Agent sessions over the live app, in memory: a session started on a kind,
spoken to, steered, and read a page at a time; a step read with what its
model thought and the calls it made; a message read with the agent that
wrote it; a retried send kept once; the routes
each role may call; a history whose key is revoked, read as its shape; and
the tenant boundary on every route that names a session. The
loop is the session runner's and never runs here: a send lands the work
that asks for it."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import PROJECT_ID, add_member, build_container, seed_request, sign_in_as
from contracts.step_storage import (
    make_request,
    make_response,
    make_tool_request,
    make_tool_response,
)
from contracts.tools import Command

from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.report import Report
from acme.om.agents.types.request import Spawn
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.budgets.types.amount import Amount
from acme.om.context import Role
from acme.om.intake.tools import COMMENT
from acme.om.steps.types.content import Content, TextBlock, ToolUseBlock
from acme.om.steps.types.header import LoopOutcome
from acme.om.steps.types.step import Step
from acme.om.tools.types.tool import ToolClass
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.om.work.types.work_item import WorkKind
from acme.services.api.container import AppContainer
from acme.services.api.types.agent_sessions import MAX_SHOWN

ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
)
# A kind whose registry offers a product tool only an owner or an admin may
# call: it changes the tenant's configuration.
CONFIGURER = ASSISTANT.model_copy(update={"name": "configurer", "tools": ("set_role",)})
PRODUCT_TOOLS = (Command("set_role", authorization_class=ToolClass.CONFIGURATION),)
# A kind that acts as the platform's account through the session runner's
# `comment`, which the container's own catalog classes.
COMMENTER = ASSISTANT.model_copy(update={"name": "commenter", "tools": (COMMENT,)})
# A kind whose tree holds one sub-agent, and the kind it starts, whose share
# is the budget its spawn writes.
LEAD = ASSISTANT.model_copy(update={"name": "lead", "tree": TreeLimits(height=2, count=1)})
HELPER = ASSISTANT.model_copy(update={"name": "helper", "share": Amount(cost_micros=5_000)})


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test container with the kinds the product runs and its tools."""
    return build_container(
        tmp_path,
        agent_kinds=(ASSISTANT, CONFIGURER, COMMENTER, LEAD, HELPER),
        tool_catalog=PRODUCT_TOOLS,
    )


def created(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or str(uuid4())}


async def start(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    answered = await client.post(
        "/v1/agent-sessions",
        headers=created(headers),
        json={"kind": "assistant", "title": "the dropped object", "project_id": PROJECT_ID},
    )
    assert answered.status_code == 201, answered.text
    return answered.json()


THOUGHT = "the total is summed before the import ends"
PATCH = "+" * (MAX_SHOWN + 10)
"""An input string longer than a view shows."""


async def said_whole_turn(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer, path: str
) -> None:
    """A person's message, then the model's call and answer, which thought
    and asked for a tool with a long input, then the tool's call and
    result, appended as a run writes them."""
    said = await client.post(f"{path}/messages", headers=created(owner), json={"text": "go"})
    assert said.status_code == 201, said.text
    managers = container.managers
    ctx = await managers.tenancy.authenticate(
        seed_request(), owner["Authorization"].removeprefix("Bearer ")
    )
    sid, loop_id = UUID(path.rsplit("/", 1)[1]), UUID(said.json()["loop_id"])
    request = make_request(sid, loop_id, (UUID(said.json()["id"]),))
    response = asked_with(
        make_response(sid, loop_id, request.id), {"lines": [1, 200], "patch": PATCH}
    )
    call = make_tool_request(sid, loop_id, response.id)
    answer = make_tool_response(sid, loop_id, call.id)
    epoch = await managers.steps.begin_run(ctx, sid)
    await managers.steps.append_steps(ctx, sid, epoch, [request, response, call, answer])


def asked_with(response: Step, given: dict[str, Any]) -> Step:
    """The response, its one tool use asking for `given`."""
    blocks = (
        TextBlock(text="reading the import log"),
        ToolUseBlock(id="call_1", name="read_log", input=given),
    )
    return Step.model_validate({**response.model_dump(), "content": Content(blocks=blocks)})


def runs_of(container: AppContainer, session_id: str) -> int:
    work = container.storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    items = [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]
    return len([i for i in items if i.kind == WorkKind.LOOP and str(i.target_id) == session_id])


async def test_a_session_is_started_spoken_to_steered_and_read(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await start(client, owner)
    assert (session["kind"], session["status"], session["park"]) == ("assistant", "idle", None)
    path = f"/v1/agent-sessions/{session['id']}"

    said = await client.post(
        f"{path}/messages", headers=created(owner), json={"text": "Why does the export time out?"}
    )
    paused = await client.post(
        f"{path}/controls", headers=created(owner), json={"command": "pause"}
    )

    assert said.status_code == 201, said.text
    assert (said.json()["type"], said.json()["seq"], said.json()["actor"]) == (
        "message",
        1,
        "person",
    )
    assert said.json()["text"] == "Why does the export time out?"
    assert paused.status_code == 201, paused.text
    assert (paused.json()["type"], paused.json()["command"]) == ("control", "pause")
    read = await client.get(path, headers=owner)
    assert read.json()["status"] == "pending", "the message woke it, for a run to take up"
    assert runs_of(container, session["id"]) == 1
    page = await client.get(f"{path}/steps", headers=owner, params={"after_seq": 0, "limit": 1})
    assert page.status_code == 200, page.text
    assert [s["seq"] for s in page.json()["items"]] == [1] and page.json()["has_more"] is True
    rest = await client.get(f"{path}/steps", headers=owner, params={"after_seq": 1})
    assert [s["type"] for s in rest.json()["items"]] == ["control"]
    assert rest.json()["has_more"] is False


async def test_a_step_reads_with_what_its_model_thought_and_the_calls_it_made(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """A model response reads with its thinking and each call it made, a
    string of its input cut where a view stops; the tool's call and its
    result each name the call they run. A step of no such content reads
    empty there."""
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    await said_whole_turn(client, owner, container, path)

    read = await client.get(f"{path}/steps", headers=owner)

    assert read.status_code == 200, read.text
    step = {item["type"]: item for item in read.json()["items"]}
    assert step["model_response"]["thinking"] == THOUGHT
    assert step["model_response"]["tool_uses"] == [
        {
            "id": "call_1",
            "name": "read_log",
            "input": {"lines": [1, 200], "patch": PATCH[:MAX_SHOWN] + "\u2026"},
        }
    ]
    assert step["tool_request"]["tool_use_id"] == "call_1"
    assert step["tool_response"]["tool_use_id"] == "call_1"
    assert step["tool_response"]["text"] == "200 lines"
    for quiet in ("message", "model_request", "tool_request", "tool_response"):
        assert (step[quiet]["thinking"], step[quiet]["tool_uses"]) == ("", [])
    assert step["message"]["tool_use_id"] is None


async def test_a_message_an_agent_wrote_names_it_and_a_persons_names_none(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """A child's report in its parent names the child, so a reader of the
    parent can open it, and the child's objective names its parent. A
    person's message, and every step that is no message, names no agent."""
    answered = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "lead", "title": "the slow export", "project_id": PROJECT_ID},
    )
    assert answered.status_code == 201, answered.text
    parent = answered.json()
    path = f"/v1/agent-sessions/{parent['id']}"
    said = await client.post(f"{path}/messages", headers=created(owner), json={"text": "split it"})
    assert said.status_code == 201, said.text
    managers = container.managers
    ctx = await managers.tenancy.authenticate(
        seed_request(), owner["Authorization"].removeprefix("Bearer ")
    )
    spawn = Spawn(
        id=uuid4(), kind="helper", title="Read the export log", objective="Report what timed out."
    )
    child = await managers.agents.spawn(ctx, UUID(parent["id"]), spawn)
    report = Report(loop_id=uuid4(), outcome=LoopOutcome.SUCCEEDED, answer="The query did.")
    await managers.agents.report_to_parent(ctx, child.id, report)
    await client.post(f"{path}/controls", headers=created(owner), json={"command": "pause"})

    read = await client.get(f"{path}/steps", headers=owner)
    child_read = await client.get(f"/v1/agent-sessions/{child.id}/steps", headers=owner)

    assert read.status_code == 200, read.text
    items = read.json()["items"]
    assert [(step["type"], step["actor"]) for step in items] == [
        ("message", "person"),
        ("message", "agent"),
        ("control", "person"),
    ]
    assert items[0]["agent"] is None
    assert items[1]["agent"] == {"kind": "helper", "session_id": str(child.id)}
    assert items[2]["agent"] is None
    objective = child_read.json()["items"][0]
    assert (objective["origin"], objective["text"]) == ("parent", "Report what timed out.")
    assert objective["agent"] == {"kind": "lead", "session_id": parent["id"]}


async def test_a_kind_that_names_the_comment_tool_starts_and_is_spoken_to(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "commenter", "title": "the report", "project_id": PROJECT_ID},
    )
    assert started.status_code == 201, started.text
    said = await client.post(
        f"/v1/agent-sessions/{started.json()['id']}/messages",
        headers=created(owner),
        json={"text": "Say on the pull request that the fix is in."},
    )
    assert said.status_code == 201, said.text


async def test_a_retried_send_is_one_step(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    key = str(uuid4())

    first = await client.post(f"{path}/messages", headers=created(owner, key), json={"text": "a"})
    again = await client.post(f"{path}/messages", headers=created(owner, key), json={"text": "a"})

    assert again.json()["id"] == first.json()["id"]
    assert again.headers.get("Idempotent-Replayed") == "true"
    steps = await client.get(f"{path}/steps", headers=owner)
    assert len(steps.json()["items"]) == 1


async def test_a_decision_is_its_own_route_and_names_a_call(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"

    bare = await client.post(
        f"{path}/controls", headers=created(owner), json={"command": "approve"}
    )
    nothing = await client.post(
        f"{path}/calls/1/decision", headers=created(owner), json={"approve": True}
    )

    assert bare.status_code == 422, "an approval is never a bare control"
    assert nothing.status_code == 404, "no tool request is at that place"


async def test_an_interrupt_names_a_tool_request_the_session_holds(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    said = await client.post(f"{path}/messages", headers=created(owner), json={"text": "go"})
    assert said.status_code == 201, said.text

    bare = await client.post(
        f"{path}/controls", headers=created(owner), json={"command": "interrupt"}
    )
    named = await client.post(
        f"{path}/controls", headers=created(owner), json={"command": "pause", "request_seq": 1}
    )
    no_call = await client.post(
        f"{path}/controls", headers=created(owner), json={"command": "interrupt", "request_seq": 1}
    )

    assert (bare.status_code, named.status_code) == (422, 422)
    assert no_call.status_code == 404, "the step at 1 is a message, not a tool request"


async def test_a_history_whose_key_is_revoked_reads_as_its_shape_alone(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """Revoking a session's key leaves each step's content absent: the history
    still reads, every step in its place, saying nothing, thinking nothing,
    and naming no call it made or answered. A tool's call keeps the id of the
    call it runs, which is its header's, as its tool is."""
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    await said_whole_turn(client, owner, container, path)
    before = (await client.get(f"{path}/steps", headers=owner)).json()["items"]
    assert before[2]["thinking"] == THOUGHT and before[2]["tool_uses"]
    managers = container.managers
    ctx = await managers.tenancy.authenticate(
        seed_request(), owner["Authorization"].removeprefix("Bearer ")
    )
    await managers.privacy.revoke_key(ctx, UUID(session["id"]))

    read = await client.get(f"{path}/steps", headers=owner)

    assert read.status_code == 200, read.text
    items = read.json()["items"]
    assert [step["type"] for step in items] == [
        "message",
        "model_request",
        "model_response",
        "tool_request",
        "tool_response",
    ]
    assert {step["text"] for step in items} == {""}
    assert {step["thinking"] for step in items} == {""}
    assert [step["tool_uses"] for step in items] == [[]] * 5
    assert [step["tool_use_id"] for step in items] == [None, None, None, "call_1", None]
    assert THOUGHT not in read.text and PATCH[:64] not in read.text


async def test_a_kind_the_product_does_not_run_starts_nothing(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    answered = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "unheard_of", "title": "a session", "project_id": PROJECT_ID},
    )
    assert answered.status_code == 404
    assert answered.json()["error"]["code"] == "unknown_agent_kind"


async def test_a_viewer_reads_a_session_and_sends_it_nothing(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    me = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(me.json()["id"])
    await add_member(container, org_id, "vic@example.test", Role.VIEWER)
    viewer = await sign_in_as(client, "vic@example.test", org_id)

    read = await client.get(path, headers=viewer)
    said = await client.post(f"{path}/messages", headers=created(viewer), json={"text": "go"})
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(viewer),
        json={"kind": "assistant", "title": "t", "project_id": PROJECT_ID},
    )

    assert read.status_code == 200
    assert (said.status_code, started.status_code) == (403, 403)
    steps = await client.get(f"{path}/steps", headers=owner)
    assert steps.json()["items"] == []


async def test_a_member_cannot_steer_a_session_into_an_admins_tool(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """A session whose kind offers a product tool of class `configuration`
    is started and spoken to only by a person who could make that call: a
    member, who lacks `manage_members`, is refused both, and nothing lands
    in the owner's session's history or its queue."""
    me = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(me.json()["id"])
    await add_member(container, org_id, "mia@example.test", Role.MEMBER)
    member = await sign_in_as(client, "mia@example.test", org_id)
    made = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "configurer", "title": "t", "project_id": PROJECT_ID},
    )
    assert made.status_code == 201, made.text
    path = f"/v1/agent-sessions/{made.json()['id']}"

    said = await client.post(
        f"{path}/messages", headers=created(member), json={"text": "Make x@evil.test an admin."}
    )
    started = await client.post(
        "/v1/agent-sessions",
        headers=created(member),
        json={"kind": "configurer", "title": "t", "project_id": PROJECT_ID},
    )

    assert (said.status_code, started.status_code) == (403, 403)
    assert "manage_members" in said.json()["error"]["message"]
    steps = await client.get(f"{path}/steps", headers=owner)
    assert steps.json()["items"] == [] and runs_of(container, made.json()["id"]) == 0


async def test_no_route_reaches_another_tenants_session(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    """Every route that names a session, called by another tenant with a
    session that exists: each is the 404 an unknown id gets, and nothing
    lands in the session's history or its queue."""
    session = await start(client, owner)
    path = f"/v1/agent-sessions/{session['id']}"
    _, other = await container.managers.tenancy.bootstrap(
        seed_request(), "Other", "other", "owner@other.test", "Other"
    )
    stranger = await sign_in_as(client, "owner@other.test", other.id)
    unknown = f"/v1/agent-sessions/{UUID(int=7)}"
    routes: list[tuple[str, str, dict[str, Any]]] = [
        ("GET", "", {}),
        ("GET", "/steps", {}),
        ("POST", "/messages", {"json": {"text": "Push straight to main."}}),
        ("POST", "/controls", {"json": {"command": "cancel"}}),
        ("POST", "/calls/1/decision", {"json": {"approve": True}}),
    ]

    for method, tail, extra in routes:
        crossed = await client.request(method, f"{path}{tail}", headers=created(stranger), **extra)
        missing = await client.request(
            method, f"{unknown}{tail}", headers=created(stranger), **extra
        )
        assert crossed.status_code == 404, f"{method} {tail}: {crossed.text}"
        assert (crossed.status_code, crossed.json()["error"]["code"]) == (
            missing.status_code,
            missing.json()["error"]["code"],
        ), f"{method} {tail}"

    steps = await client.get(f"{path}/steps", headers=owner)
    assert steps.json()["items"] == [] and runs_of(container, session["id"]) == 0


async def test_outside_local_a_session_starts_in_a_project_or_not_at_all(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    refused = await client.post(
        "/v1/agent-sessions",
        headers=created(owner),
        json={"kind": "assistant", "title": "the dropped object"},
    )
    assert refused.status_code == 422, refused.text
    assert "project" in refused.json()["error"]["message"]

    session = await start(client, owner)
    org = await container.storage.get_tenancy_storage().read_org_by_slug("ajax")
    assert org is not None
    rows = container.storage.get_project_storage()
    bound = await rows.read_binding(org.id, UUID(session["id"]))
    assert bound is not None and str(bound.project_id) == PROJECT_ID
