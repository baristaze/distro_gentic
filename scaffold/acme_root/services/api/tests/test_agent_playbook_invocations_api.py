"""An agent playbook invoked and pinned over the API. A person invokes the latest
version into a session they may instruct, once a version, and its brief
arrives as their message; a viewer invokes none, and a name with no
version is not found. A person who manages the tenant pins one to a kind
as its kind manual, which a session started after holds as its standing text
and one started before does not; a member pins none, and a kind, a
project, or a brief no session could hold whole is refused."""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from api_support import build_container
from contracts.loops import ASSISTANT, tools
from tenant_support import person, refused, tenant

from acme.om.agents.types.request import MAX_STANDING
from acme.om.base import new_id
from acme.om.context import Role
from acme.services.api.container import AppContainer

DRAFT = {
    "name": "release-check",
    "description": "What a release needs before it ships.",
    "body": "1. Run the checks.\n2. Read the diff.\n3. Never push to main.",
    "gates": [{"tool": "send", "decision": "approve"}],
}
PROJECT = {"name": "the ledger", "repository": {"host": "github.com", "path": "octo/ledger"}}


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """The test container with a kind a session starts on, and its tools."""
    return build_container(tmp_path, agent_kinds=(ASSISTANT,), tool_catalog=tuple(tools().values()))


async def started(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    """A session of the assistant, in a project of the tenant's."""
    project = await client.post("/v1/projects", headers=headers, json=PROJECT)
    if project.status_code != 201:
        listed = await client.get("/v1/projects", headers=headers)
        project_id = listed.json()[0]["id"]
    else:
        project_id = project.json()["id"]
    session = await client.post(
        "/v1/agent-sessions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"kind": ASSISTANT.name, "title": "the ledger", "project_id": project_id},
    )
    assert session.status_code == 201, session.text
    return session.json()["id"]


async def test_a_person_invokes_a_agent_playbook_into_a_session_once_a_version(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    await client.post("/v1/agent-playbooks", headers=ajax.owner, json=DRAFT)
    session_id = await started(client, ajax.owner)
    url = "/v1/agent-playbooks/release-check/invocations"
    invoked = await client.post(url, headers=ajax.owner, json={"session_id": session_id})
    assert invoked.status_code == 201, invoked.text
    assert invoked.json()["session_id"] == session_id
    assert (invoked.json()["version"], invoked.json()["pinned"]) == (1, False)
    again = await client.post(url, headers=ajax.owner, json={"session_id": session_id})
    assert again.json() == invoked.json()
    steps = await client.get(f"/v1/agent-sessions/{session_id}/steps", headers=ajax.owner)
    (brief,) = [step for step in steps.json()["items"] if step["type"] == "message"]
    assert "name: release-check" in brief["text"]

    viewer = await person(client, container, ajax.org_id, Role.VIEWER)
    refused(
        await client.post(url, headers=viewer, json={"session_id": session_id}),
        403,
        "not_authorized",
    )
    bravo = await tenant(client, container, "bravo")
    await client.post("/v1/agent-playbooks", headers=bravo.owner, json=DRAFT)
    other = await client.post(url, headers=bravo.owner, json={"session_id": session_id})
    assert other.status_code in (403, 404), other.text
    missing = "/v1/agent-playbooks/no-such-agent-playbook/invocations"
    refused(
        await client.post(missing, headers=ajax.owner, json={"session_id": session_id}),
        404,
        "not_found",
    )


async def test_a_pinned_agent_playbook_is_the_standing_text_of_a_session_started_after(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    await client.post("/v1/agent-playbooks", headers=ajax.owner, json=DRAFT)
    before = await started(client, ajax.owner)
    pin = {"kind": ASSISTANT.name, "name": "release-check"}
    pinned = await client.put("/v1/agent-playbook-pins", headers=ajax.owner, json=pin)
    assert pinned.status_code == 200, pinned.text
    assert (pinned.json()["version"], pinned.json()["project_id"]) == (1, None)
    listed = await client.get("/v1/agent-playbook-pins", headers=ajax.owner)
    assert listed.json() == [pinned.json()]
    after = await started(client, ajax.owner)

    async def standing(session_id: str) -> list[str]:
        steps = await client.get(f"/v1/agent-sessions/{session_id}/steps", headers=ajax.owner)
        return [s["text"] for s in steps.json()["items"] if s["type"] == "switched"]

    assert await standing(before) == []
    (held,) = await standing(after)
    assert "name: release-check" in held and "Never push to main." in held

    unpinned = await client.request(
        "DELETE", "/v1/agent-playbook-pins", headers=ajax.owner, params={"kind": ASSISTANT.name}
    )
    assert unpinned.status_code == 200, unpinned.text
    assert unpinned.json() == pinned.json()
    gone = await client.request(
        "DELETE", "/v1/agent-playbook-pins", headers=ajax.owner, params={"kind": ASSISTANT.name}
    )
    refused(gone, 404, "not_found")


async def test_only_one_who_manages_the_tenant_pins_and_a_brief_too_long_is_refused(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    ajax = await tenant(client, container, "ajax")
    await client.post("/v1/agent-playbooks", headers=ajax.owner, json=DRAFT)
    pin = {"kind": ASSISTANT.name, "name": "release-check"}
    member = await person(client, container, ajax.org_id, Role.MEMBER)
    refused(
        await client.put("/v1/agent-playbook-pins", headers=member, json=pin), 403, "not_authorized"
    )
    unknown = {**pin, "kind": "no-such-kind"}
    refused(
        await client.put("/v1/agent-playbook-pins", headers=ajax.owner, json=unknown),
        404,
        "unknown_agent_kind",
    )
    elsewhere = {**pin, "project_id": str(new_id())}
    refused(
        await client.put("/v1/agent-playbook-pins", headers=ajax.owner, json=elsewhere),
        404,
        "not_found",
    )
    long = {**DRAFT, "name": "long-kind-manual", "body": "x" * MAX_STANDING}
    assert (
        await client.post("/v1/agent-playbooks", headers=ajax.owner, json=long)
    ).status_code == 201
    too_long = {**pin, "name": "long-kind-manual"}
    refused(
        await client.put("/v1/agent-playbook-pins", headers=ajax.owner, json=too_long),
        422,
        "validation_failed",
    )
    assert (await client.get("/v1/agent-playbook-pins", headers=member)).json() == []
