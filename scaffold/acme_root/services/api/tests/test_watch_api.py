"""The watch's routes over the live app, in memory. A live read is served
by its handle alone and reads only the session it was issued for. A person
takes control, runs a command recorded as theirs on the host that holds the
workspace, and gives it back."""

from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import build_container, seed_request
from contracts.agent_session_storage import make_session
from test_hosts_api import ASSISTANT, a_host, a_pool, a_token, bearer, created, tenant_of

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id
from acme.om.exceptions import Unavailable
from acme.om.relay.types.exec import ExecOutcome, ExecOutput, ExecResult
from acme.om.retention.crossing import CrossingKind, declared
from acme.om.steps.types.stream import TextPart
from acme.services.api.container import AppContainer

KEY = "a-live-read-key-for-tests-only-32+"
SPEC = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    return build_container(tmp_path, agent_kinds=(ASSISTANT,), live_read_key=KEY)


def part(session_id: UUID, step_id: UUID, n: int) -> TextPart:
    return TextPart(session_id=session_id, step_id=step_id, n=n, index=0, text=f"word{n} ")


async def test_a_live_read_is_served_by_its_handle_alone_for_its_own_session(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    ctx = await tenant_of(container, owner)
    mine = await container.managers.agent_sessions.create_session(ctx, make_session())
    other = await container.managers.agent_sessions.create_session(ctx, make_session())
    step = new_id()
    for n in range(3):
        container.stream.emit(part(mine.id, step, n))
    container.stream.emit(part(other.id, new_id(), 0))
    await container.stream.flush()

    opened = await client.post(f"/v1/agent-sessions/{mine.id}/live", headers=owner)
    assert opened.status_code == 200, opened.text
    handle = opened.json()["handle"]

    # No credential but the handle.
    read = await client.get("/v1/live", params={"handle": handle})
    assert read.status_code == 200, read.text
    (stream,) = read.json()["streams"]
    assert stream["step_id"] == str(step) and [p["n"] for p in stream["parts"]] == [0, 1, 2]

    container.stream.emit(part(mine.id, step, 3))
    await container.stream.flush()
    resumed = await client.get("/v1/live", params={"handle": handle, "after": f"{step}:2"})
    assert [p["n"] for p in resumed.json()["streams"][0]["parts"]] == [3]

    body, mac = handle.split(".")
    for forged in (f"{body}.{mac[::-1]}", f"{body}A.{mac}"):
        refused = await client.get("/v1/live", params={"handle": forged})
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"]["code"] == "live_read_refused"
    unread = await client.get("/v1/live", params={"handle": handle, "after": "not-a-mark"})
    assert unread.json()["error"]["code"] == "validation_failed"


async def test_with_no_key_every_live_read_is_refused(tmp_path: Path) -> None:
    keyless = build_container(tmp_path / "keyless")
    assert keyless.settings.live_read_key is None
    ctx, _ = await keyless.managers.tenancy.bootstrap(
        seed_request(), "Ajax", "ajax", "ann@ajax.test", "Ann"
    )
    session = await keyless.managers.agent_sessions.create_session(ctx, make_session())
    watch = keyless.services.get_watch_service()
    with pytest.raises(Unavailable):
        await watch.open_live(ctx, session.id)


async def test_a_person_takes_control_runs_a_command_as_theirs_and_gives_it_back(
    client: httpx.AsyncClient, owner: dict[str, str], container: AppContainer
) -> None:
    pool_id = await a_pool(client, owner)
    host = await a_host(client, await a_token(client, owner, pool_id))
    ctx = await tenant_of(container, owner)
    managers = container.managers
    session = await managers.agent_sessions.create_session(ctx, make_session())
    await managers.hosts.place_session(ctx, session.id, UUID(pool_id))
    await managers.relay.bind_workspace(ctx, session.id, UUID(host["host_id"]), "/srv/work/s1")
    await managers.workspaces.pinned(ctx, session.id, SPEC)
    control = f"/v1/agent-sessions/{session.id}/control"
    command = {"argv": ["make", "test"]}

    early = await client.post(f"{control}/commands", headers=created(owner), json=command)
    assert early.json()["error"]["code"] == "not_handed_over", early.text

    taken = await client.post(control, headers=owner)
    assert taken.status_code == 200, taken.text
    assert taken.json()["park"]["reason"] == "handover"

    sent = await client.post(f"{control}/commands", headers=created(owner), json=command)
    assert sent.status_code == 201, sent.text
    run = sent.json()
    assert run["user_id"] == str(ctx.user_id) and run["state"] == "queued"

    claimed = await client.post(
        "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
    )
    assert claimed.json()["item"]["payload"]["item_id"] == run["item_id"], claimed.text
    identity = await managers.hosts.authenticate(seed_request(), host["token"])
    result = ExecResult(outcome=ExecOutcome(exit_code=0), output=ExecOutput(stdout="ok\n"))
    data = result.model_dump_json().encode()
    await managers.relay.push_result(
        seed_request(), identity, UUID(run["item_id"]), declared(CrossingKind.RESULT, data), data
    )

    ended = await client.get(f"{control}/commands/{run['command_key']}", headers=owner)
    assert ended.status_code == 200, ended.text
    assert (ended.json()["state"], ended.json()["exit_code"], ended.json()["stdout"]) == (
        "done",
        0,
        "ok\n",
    )
    unknown = await client.get(f"{control}/commands/{uuid4()}", headers=owner)
    assert unknown.status_code == 404

    back = await client.post(
        f"{control}/give-back", headers=owner, json={"summary": "Tests pass; over to you."}
    )
    assert back.status_code == 200, back.text
    assert back.json()["park"] is None
