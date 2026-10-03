"""The watch end to end over the compose stack's Postgres: a viewer reads a
session live by its handle alone, and a person takes control, runs a
command the host claims and settles through its own routes, recorded in
the tenant's event stream as theirs, while the run that held the loop is
fenced, and gives it back."""

import base64
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.agent_session_storage import make_session
from test_hosts_api import a_host, a_pool, a_token, bearer, created, tenant_of
from test_rate_limits_integration import over_the_stack

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id
from acme.om.exceptions import StaleWriter
from acme.om.relay.types.exec import ExecOutcome, ExecOutput, ExecResult
from acme.om.steps.rules import message_step
from acme.om.steps.types.stream import TextPart
from acme.om.watch.impl.manager import SENT

pytestmark = pytest.mark.integration

KEY = "an-integration-live-read-key-32-chars"
SPEC = IsolationSpec(mode=IsolationMode.CONTAINER, egress=EgressPolicy(mode=EgressMode.NONE))


async def test_a_viewer_watches_and_a_person_takes_control_over_the_stack(
    tmp_path: Path,
) -> None:
    async with over_the_stack(tmp_path, live_read_key=KEY) as (container, client, owner):
        managers = container.managers
        pool_id = await a_pool(client, owner)
        host = await a_host(client, await a_token(client, owner, pool_id))
        ctx = await tenant_of(container, owner)
        session = await managers.agent_sessions.create_session(ctx, make_session())
        await managers.hosts.place_session(ctx, session.id, UUID(pool_id))
        await managers.relay.bind_workspace(ctx, session.id, UUID(host["host_id"]), "/srv/w")
        await managers.workspaces.pinned(ctx, session.id, SPEC)
        agents_epoch = await managers.steps.begin_run(ctx, session.id)

        step = new_id()
        container.stream.emit(
            TextPart(session_id=session.id, step_id=step, n=0, index=0, text="Looking")
        )
        await container.stream.flush()
        opened = await client.post(f"/v1/agent-sessions/{session.id}/live", headers=owner)
        read = await client.get("/v1/live", params={"handle": opened.json()["handle"]})
        assert read.status_code == 200, read.text
        assert read.json()["streams"][0]["parts"][0]["text"] == "Looking"

        control = f"/v1/agent-sessions/{session.id}/control"
        assert (await client.post(control, headers=owner)).status_code == 200
        note = message_step(new_id(), session.created_at, session.id, ctx, "still mine")
        with pytest.raises(StaleWriter):
            await managers.steps.append_steps(ctx, session.id, agents_epoch, [note])

        sent = await client.post(
            f"{control}/commands", headers=created(owner), json={"argv": ["make", "test"]}
        )
        assert sent.status_code == 201, sent.text
        run = sent.json()
        claimed = await client.post(
            "/v1/hosts/me/claims", headers=bearer(host["token"]), json={"exec_version": 1}
        )
        item_id = claimed.json()["item"]["payload"]["item_id"]
        assert item_id == run["item_id"], claimed.text
        held = await client.get(f"/v1/hosts/me/exec/{item_id}", headers=bearer(host["token"]))
        assert held.json()["request"]["argv"] == ["make", "test"]
        result = ExecResult(outcome=ExecOutcome(exit_code=0), output=ExecOutput(stdout="ok\n"))
        data = result.model_dump_json().encode()
        pushed = await client.post(
            f"/v1/hosts/me/exec/{item_id}/result",
            headers=bearer(host["token"]),
            json={
                "data": base64.b64encode(data).decode(),
                "crossing": {
                    "kind": "result",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                },
            },
        )
        assert pushed.status_code == 204, pushed.text

        ended = await client.get(f"{control}/commands/{run['command_key']}", headers=owner)
        assert (ended.json()["state"], ended.json()["stdout"]) == ("done", "ok\n")
        events = await managers.events.get_events(ctx, 0, 200)
        (record,) = [event for event in events if event.kind == SENT]
        assert (record.actor_id, str(record.target_id)) == (ctx.user_id, item_id)

        back = await client.post(f"{control}/give-back", headers=owner, json={"summary": "Done."})
        assert back.status_code == 200 and back.json()["park"] is None


async def test_a_handle_reads_only_its_own_sessions_streams_through_the_shared_cache(
    tmp_path: Path,
) -> None:
    """Two sessions stream into the compose stack's Valkey at once. Each
    handle reads its own session's stream and nothing of the other's, a
    part that names one session's step from the other included."""
    async with over_the_stack(tmp_path, live_read_key=KEY) as (container, client, owner):
        assert container.infra.get_streams().describe().startswith("streams=valkey")
        ctx = await tenant_of(container, owner)
        mine = await container.managers.agent_sessions.create_session(ctx, make_session())
        theirs = await container.managers.agent_sessions.create_session(ctx, make_session())
        my_step, their_step = new_id(), new_id()
        for n in range(3):
            container.stream.emit(
                TextPart(session_id=mine.id, step_id=my_step, n=n, index=0, text=f"mine {n}")
            )
            container.stream.emit(
                TextPart(session_id=theirs.id, step_id=their_step, n=n, index=0, text="theirs")
            )
        container.stream.emit(
            TextPart(session_id=theirs.id, step_id=my_step, n=3, index=0, text="theirs")
        )
        await container.stream.flush()

        async def read(session_id: UUID) -> list[dict[str, Any]]:
            opened = await client.post(f"/v1/agent-sessions/{session_id}/live", headers=owner)
            read = await client.get("/v1/live", params={"handle": opened.json()["handle"]})
            assert read.status_code == 200, read.text
            assert read.json()["session_id"] == str(session_id)
            return read.json()["streams"]

        (own,) = await read(mine.id)
        assert own["step_id"] == str(my_step)
        assert "".join(part["text"] for part in own["parts"]) == "mine 0mine 1mine 2"
        other = await read(theirs.id)
        assert {stream["step_id"] for stream in other} == {str(their_step), str(my_step)}
        texts = {part["text"] for stream in other for part in stream["parts"]}
        assert {text.replace("theirs", "") for text in texts} == {""}
