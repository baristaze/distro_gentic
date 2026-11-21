"""The example assistant: the local and the staging stacks offer it, and no
other. Asked a question, it reads the org's files in the request and
answers there, with no call a person approves. Its loop runs here as the
session runner runs one: each call through the trust wall, which audits
it, and the session's agent playbook gates, and the agent knowledge its
subject triggers recalled before its first model call."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from api_support import build_container, open_spend_account, sign_in

from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers import ModelProvidersInterface
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.types.kind import AgentKind
from acme.om.trust.impl.manager import CALL_AUDITED
from acme.services.api.assistant import ASSISTANT, LIST_FILES, offered
from acme.services.api.container import AppContainer

from contracts.loops import call, reply, said
from contracts.media_storage import make_file


@pytest.fixture
def providers() -> ModelProvidersInterface:
    return scripted_model_providers()


@pytest.fixture
def container(tmp_path: Path, providers: ModelProvidersInterface) -> AppContainer:
    return build_container(
        tmp_path,
        integrations=IntegrationsOverImpl(IdentityProviderTwinImpl(), providers),
        environment="local",
    )


@pytest.fixture
async def owner(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    """The owner, signed in, the tenant's account open: a loop's calls have
    someone to charge."""
    headers = await sign_in(client, container)
    await open_spend_account(container, headers)
    return headers


@pytest.mark.parametrize(
    ("environment", "declared", "kinds"),
    [
        ("local", (), ("assistant",)),
        ("staging", (), ("assistant",)),
        ("production", (), ()),
        ("test", (), ()),
        ("local", (ASSISTANT.model_copy(update={"name": "product"}),), ()),
    ],
)
def test_the_assistant_is_offered_in_the_local_and_staging_stacks_alone(
    environment: str, declared: tuple[AgentKind, ...], kinds: tuple[str, ...]
) -> None:
    """A product that declares its own kinds is offered none of the example."""

    def never() -> object:
        raise AssertionError("no tool is built that reads nothing")

    offered_kinds, offered_tools = offered(environment, declared, never)  # pyright: ignore[reportArgumentType]

    assert tuple(kind.name for kind in offered_kinds) == kinds
    assert tuple(tool.spec.name for tool in offered_tools) == ((LIST_FILES,) if kinds else ())


async def test_the_assistant_reads_the_orgs_files_and_answers_in_the_request(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    providers: ModelProvidersInterface,
) -> None:
    org = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(org.json()["id"])
    await container.storage.get_media_storage().create_file(org_id, make_file(), ())
    twin = providers.get(ProviderName.ANTHROPIC)
    assert isinstance(twin, ModelProviderScriptedImpl)
    twin.add(reply(call(LIST_FILES)), reply(said("The org keeps one file, notes.pdf.")))

    asked = await client.post(
        "/v1/agent-sessions/questions",
        headers=owner,
        json={"kind": ASSISTANT.name, "title": "files", "text": "Which files do we keep?"},
    )

    assert asked.status_code == 200, asked.text
    frames = [f for f in asked.text.split("\n\n") if f.strip()]
    end = json.loads(frames[-1].split("data: ", 1)[1])
    assert (end["end"], end["outcome"]) == ("ended", "succeeded")
    steps = await client.get(f"/v1/agent-sessions/{end['agent_session_id']}/steps", headers=owner)
    (read,) = [s for s in steps.json()["items"] if s["type"] == "tool_response"]
    assert read["failure"] is None and "notes.pdf" in read["text"]


async def ask(client: httpx.AsyncClient, owner: dict[str, str], text: str) -> list[dict[str, Any]]:
    """The session's steps once the assistant answered `text` in the request."""
    asked = await client.post(
        "/v1/agent-sessions/questions",
        headers=owner,
        json={"kind": ASSISTANT.name, "title": "files", "text": text},
    )
    assert asked.status_code == 200, asked.text
    frames = [f for f in asked.text.split("\n\n") if f.strip()]
    end = json.loads(frames[-1].split("data: ", 1)[1])
    assert (end["end"], end["outcome"]) == ("ended", "succeeded")
    steps = await client.get(f"/v1/agent-sessions/{end['agent_session_id']}/steps", headers=owner)
    return steps.json()["items"]


async def test_a_question_runs_its_calls_through_the_wall_and_the_gates_and_recalls(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    providers: ModelProvidersInterface,
) -> None:
    org = await client.get("/v1/orgs/current", headers=owner)
    org_id = UUID(org.json()["id"])
    await container.storage.get_media_storage().create_file(org_id, make_file(), ())
    entry = {"title": "the files", "trigger": ["files"], "text": "The notes are kept as PDFs."}
    keyed = {**owner, "Idempotency-Key": "write-the-files-entry"}
    assert (await client.post("/v1/agent-knowledge", headers=keyed, json=entry)).is_success
    twin = providers.get(ProviderName.ANTHROPIC)
    assert isinstance(twin, ModelProviderScriptedImpl)

    # The call runs through the trust wall, which audits it, and the entry
    # the question triggers arrives before the first model call.
    twin.add(reply(call(LIST_FILES)), reply(said("One file.")))
    steps = await ask(client, owner, "Which files do we keep?")

    types = [s["type"] for s in steps]
    assert "event" in types, "the entry recalled"
    assert types.index("event") < types.index("model_request"), "before the first call"
    (read,) = [s for s in steps if s["type"] == "tool_response"]
    assert read["failure"] is None and "notes.pdf" in read["text"]
    events = await container.storage.get_change_event_storage().read_after(org_id, 0, 1000)
    assert [e.kind for e in events].count(CALL_AUDITED) == 1, "the call audited"

    # A playbook pinned to the kind denies the call: its gate holds it.
    playbook = {
        "name": "no-listing",
        "description": "Answers from what it knows.",
        "body": "Never list the files.",
        "gates": [{"tool": LIST_FILES, "decision": "deny"}],
    }
    assert (await client.post("/v1/agent-playbooks", headers=owner, json=playbook)).is_success
    pin = {"kind": ASSISTANT.name, "name": "no-listing"}
    assert (await client.put("/v1/agent-playbook-pins", headers=owner, json=pin)).is_success
    twin.add(reply(call(LIST_FILES)), reply(said("I may not list them.")))
    steps = await ask(client, owner, "Which files do we keep?")

    (denied,) = [s for s in steps if s["type"] == "tool_response"]
    assert "an agent playbook of this session does not allow" in denied["text"]
