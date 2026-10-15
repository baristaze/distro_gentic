"""The agent_playbooks namespace's calls: what a tenant's sessions follow,
published, brought into a session, and pinned to a kind."""

from typing import Any
from uuid import UUID, uuid4

from acme.client.transport import Transport
from acme.client.types.agent_playbooks import (
    AgentPlaybookView,
    InvocationView,
    PinView,
    PublishRequest,
)


class AgentPlaybooksCalls(Transport):
    """An agent playbook's versions, its invocations, and its pins."""

    async def agent_playbook(self, name: str) -> AgentPlaybookView:
        """The latest version of the name."""
        return AgentPlaybookView.model_validate(
            await self.request("GET", f"/v1/agent-playbooks/{name}")
        )

    async def publish_agent_playbook(self, draft: PublishRequest) -> AgentPlaybookView:
        """The next version of the draft's name, published in person."""
        published = await self.request(
            "POST", "/v1/agent-playbooks", json=draft.model_dump(mode="json", exclude_unset=True)
        )
        return AgentPlaybookView.model_validate(published)

    async def invoke_agent_playbook(
        self, name: str, agent_session_id: UUID, *, idempotency_key: str | None = None
    ) -> InvocationView:
        """The name's latest version brought into the session, in person: its
        gates hold there from now on, and its brief arrives as the caller's
        message. Invoked again, the same invocation."""
        invoked = await self.request(
            "POST",
            f"/v1/agent-playbooks/{name}/invocations",
            json={"agent_session_id": str(agent_session_id)},
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return InvocationView.model_validate(invoked)

    async def agent_playbook_pins(self) -> list[PinView]:
        """The tenant's pins, by kind, the tenant's before an agent project's."""
        return [
            PinView.model_validate(pin)
            for pin in await self.request("GET", "/v1/agent-playbook-pins")
        ]

    async def pin_agent_playbook(
        self, kind: str, name: str, *, agent_project_id: UUID | None = None
    ) -> PinView:
        """The name's latest version pinned to the kind as its kind manual, for the
        tenant, or for one agent project; each session of the kind made from now
        on holds it, and one made before keeps its own."""
        body: dict[str, Any] = {"kind": kind, "name": name}
        if agent_project_id is not None:
            body["agent_project_id"] = str(agent_project_id)
        return PinView.model_validate(
            await self.request("PUT", "/v1/agent-playbook-pins", json=body)
        )

    async def unpin_agent_playbook(
        self, kind: str, *, agent_project_id: UUID | None = None
    ) -> PinView:
        """The kind's pin for the tenant, or for one agent project, taken away."""
        params: dict[str, Any] = {"kind": kind}
        if agent_project_id is not None:
            params["agent_project_id"] = str(agent_project_id)
        unpinned = await self.request("DELETE", "/v1/agent-playbook-pins", params=params)
        return PinView.model_validate(unpinned)
