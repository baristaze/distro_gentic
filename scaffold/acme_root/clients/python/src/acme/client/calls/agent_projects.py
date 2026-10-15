"""The agent_projects namespace's calls: a tenant's agent projects, each
bound to one repository, and the read-only credential that repository is
fetched with."""

from typing import Any
from uuid import UUID, uuid4

from acme.client.transport import LIMIT_MAX, Transport
from acme.client.types.agent_projects import (
    AgentProjectView,
    FetchCredentialView,
)


class AgentProjectsCalls(Transport):
    """An agent project's making, its reads, its rename and removal, and its
    repository's fetch credential."""

    async def create_agent_project(
        self, name: str, host: str, path: str, *, idempotency_key: str | None = None
    ) -> AgentProjectView:
        """An agent project bound to the repository at `host`/`path`, which never
        moves. An owner's or an admin's. Always under an idempotency key."""
        made = await self.request(
            "POST",
            "/v1/agent-projects",
            json={"name": name, "repository": {"host": host, "path": path}},
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return AgentProjectView.model_validate(made)

    async def agent_projects(
        self, *, after: UUID | None = None, limit: int = LIMIT_MAX
    ) -> list[AgentProjectView]:
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = str(after)
        found = await self.request("GET", "/v1/agent-projects", params=params)
        return [AgentProjectView.model_validate(agent_project) for agent_project in found]

    async def agent_project(self, agent_project_id: UUID) -> AgentProjectView:
        return AgentProjectView.model_validate(
            await self.request("GET", f"/v1/agent-projects/{agent_project_id}")
        )

    async def rename_agent_project(self, agent_project_id: UUID, name: str) -> AgentProjectView:
        renamed = await self.request(
            "PATCH", f"/v1/agent-projects/{agent_project_id}", json={"name": name}
        )
        return AgentProjectView.model_validate(renamed)

    async def remove_agent_project(self, agent_project_id: UUID) -> AgentProjectView:
        """Refused with `agent_project_in_use` while a session belongs to it."""
        removed = await self.request("DELETE", f"/v1/agent-projects/{agent_project_id}")
        return AgentProjectView.model_validate(removed)

    async def put_fetch_credential(
        self, agent_project_id: UUID, username: str, password: str
    ) -> FetchCredentialView:
        """A read-only credential of the agent project's repository. The answer
        says who gave it when; nothing ever reads it back."""
        given = await self.request(
            "PUT",
            f"/v1/agent-projects/{agent_project_id}/credential",
            json={"username": username, "password": password},
        )
        return FetchCredentialView.model_validate(given)
