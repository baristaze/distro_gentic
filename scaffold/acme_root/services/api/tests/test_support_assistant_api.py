"""The support assistant, the kind behind the portal's support dock, answers
in the request that asks it. A question starts its session, the loop runs
here, its readers read the tenant's agent knowledge and agent automations,
and the answer streams back as it is written; no work item is written. Its
model call holds the kind's own tools and nothing a loop hook attached.
A local stack that ships the platform's agents offers the support
assistant in place of the example assistant, whose tool shares a name with
the platform's. The loop runs in-process, over the memory storage and the
scripted model."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import open_spend_account, sign_in

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsOverImpl
from acme.integrations.model_providers import ModelProvidersInterface
from acme.integrations.model_providers.registry import scripted_model_providers
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.kinds.support_assistant.kind import SUPPORT_ASSISTANT_KIND
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.work.storage.impl.memory import WorkStorageMemoryImpl
from acme.services.api.container import AppContainer
from acme.services.api.kinds.assistant.kind import ASSISTANT as EXAMPLE
from acme.services.api.settings import ApiSettings

from contracts.loops import call, reply, said
from contracts.platform_agents import CORPUS

Event = tuple[str, dict[str, Any]]


@pytest.fixture
def providers() -> ModelProvidersInterface:
    return scripted_model_providers()


@pytest.fixture
def container(tmp_path: Path, providers: ModelProvidersInterface) -> AppContainer:
    settings = ApiSettings.model_validate({"_env_file": None, "environment": "test"})
    return AppContainer.over(
        settings,
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderTwinImpl(), providers),
        platform_agents=PlatformAgents(corpus=CORPUS),
    )


@pytest.fixture
async def owner(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    headers = await sign_in(client, container)
    await open_spend_account(container, headers)
    return headers


def events_of(response: httpx.Response) -> list[Event]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events: list[Event] = []
    for frame in response.text.split("\n\n"):
        if frame.strip():
            fields = dict(line.split(": ", 1) for line in frame.split("\n"))
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def work_for(container: AppContainer, agent_session_id: str) -> list[str]:
    work = container.storage.get_work_storage()
    assert isinstance(work, WorkStorageMemoryImpl)
    items = [item for _, item in work._items.values()]  # pyright: ignore[reportPrivateUsage]
    return [str(i.kind) for i in items if str(i.target_id) == agent_session_id]


async def test_a_question_to_the_support_assistant_reads_and_streams_its_answer_in_the_request(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    providers: ModelProvidersInterface,
) -> None:
    twin = providers.get(ProviderName.ANTHROPIC)
    assert isinstance(twin, ModelProviderScriptedImpl)
    twin.add(
        reply(call(kinds.LIST_AGENT_AUTOMATIONS), call(kinds.SEARCH_AGENT_KNOWLEDGE, query="x")),
        reply(said("You have no agent automations yet.")),
    )

    asked = await client.post(
        "/v1/agent-sessions/questions",
        headers=owner,
        json={
            "kind": kinds.SUPPORT_ASSISTANT,
            "title": "Support",
            "text": "Which automations run?",
        },
    )

    events = events_of(asked)
    names = [name for name, _ in events]
    assert names[0] == "session" and names[-1] == "end" and "text" in names
    text = "".join(data["text"] for name, data in events if name == "text")
    assert text == "You have no agent automations yet."
    end = events[-1][1]
    assert (end["end"], end["outcome"]) == ("ended", "succeeded")
    agent_session_id = end["agent_session_id"]
    assert work_for(container, agent_session_id) == [], "no work item"
    # Both readers ran here, on the person's own permissions.
    steps = await client.get(f"/v1/agent-sessions/{agent_session_id}/steps", headers=owner)
    answers = [s for s in steps.json()["items"] if s["type"] == "tool_response"]
    assert [a["failure"] for a in answers] == [None, None], answers
    # Its model call holds its kind's tools, and nothing a loop hook attached.
    first = twin.calls[0]
    assert sorted(tool.name for tool in first.tools) == sorted(SUPPORT_ASSISTANT_KIND.tools)
    session = await client.get(f"/v1/agent-sessions/{agent_session_id}", headers=owner)
    assert session.json()["kind"] == kinds.SUPPORT_ASSISTANT


def test_a_local_stack_that_ships_the_platforms_agents_offers_no_example_beside_them(
    tmp_path: Path,
) -> None:
    settings = ApiSettings.model_validate({"_env_file": None, "environment": "local"})

    shipped = AppContainer.over(
        settings,
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderTwinImpl(), scripted_model_providers()),
        platform_agents=PlatformAgents(corpus=CORPUS),
    )
    bare = AppContainer.over(
        settings,
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        IntegrationsOverImpl(IdentityProviderTwinImpl(), scripted_model_providers()),
    )

    names = {kind.name for kind in shipped.managers.kinds.kinds}
    assert kinds.SUPPORT_ASSISTANT in names and EXAMPLE.name not in names
    assert EXAMPLE.name in {kind.name for kind in bare.managers.kinds.kinds}
