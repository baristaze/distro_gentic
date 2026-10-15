"""The connectors namespace's calls: the tool servers a tenant connects,
their credentials, their listings and review, and their attachments to a
kind."""

from typing import Any
from uuid import UUID, uuid4

from acme.client.transport import LIMIT_MAX, Transport
from acme.client.types.connectors import (
    ConnectorReviewRequest,
    ConnectorView,
    ListedToolView,
)


class ConnectorsCalls(Transport):
    """A connector's making, its credential, its listing and review, and its
    attachments."""

    async def connectors(
        self, *, after: UUID | None = None, limit: int = LIMIT_MAX
    ) -> list[ConnectorView]:
        params: dict[str, Any] = {"limit": limit}
        if after is not None:
            params["after"] = str(after)
        found = await self.request("GET", "/v1/connectors", params=params)
        return [ConnectorView.model_validate(connector) for connector in found]

    async def connector(self, connector_id: UUID) -> ConnectorView:
        read = await self.request("GET", f"/v1/connectors/{connector_id}")
        return ConnectorView.model_validate(read)

    async def connect_server(
        self,
        name: str,
        summary: str,
        *,
        url: str | None = None,
        host_server: str | None = None,
        idempotency_key: str | None = None,
    ) -> ConnectorView:
        """A server on the internet at `url`, or the server the tenant's host
        runs as `host_server`. Always under an idempotency key."""
        body: dict[str, Any] = {"name": name, "summary": summary}
        for key, value in (("url", url), ("host_server", host_server)):
            if value is not None:
                body[key] = value
        made = await self.request(
            "POST", "/v1/connectors", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return ConnectorView.model_validate(made)

    async def put_connector_credential(self, connector_id: UUID, value: str) -> ConnectorView:
        """A cloud server's credential. It goes in and never comes back."""
        given = await self.request(
            "PUT", f"/v1/connectors/{connector_id}/credential", json={"value": value}
        )
        return ConnectorView.model_validate(given)

    async def connector_listing(self, connector_id: UUID) -> list[ListedToolView]:
        """What a cloud server lists now, each tool with the hash a review names."""
        listed = await self.request("GET", f"/v1/connectors/{connector_id}/listing")
        return [ListedToolView.model_validate(tool) for tool in listed]

    async def review_connector(
        self, connector_id: UUID, review: ConnectorReviewRequest
    ) -> ConnectorView:
        """The tools a session may call, each at the hash read; in person."""
        reviewed = await self.request(
            "POST",
            f"/v1/connectors/{connector_id}/review",
            json=review.model_dump(mode="json", exclude_unset=True),
        )
        return ConnectorView.model_validate(reviewed)

    async def attach_connector(
        self,
        connector_id: UUID,
        kind: str,
        *,
        agent_project_id: UUID | None = None,
        deferred: bool = True,
    ) -> ConnectorView:
        body: dict[str, Any] = {"kind": kind, "deferred": deferred}
        if agent_project_id is not None:
            body["agent_project_id"] = str(agent_project_id)
        attached = await self.request(
            "POST", f"/v1/connectors/{connector_id}/attachments", json=body
        )
        return ConnectorView.model_validate(attached)

    async def detach_connector(
        self, connector_id: UUID, kind: str, *, agent_project_id: UUID | None = None
    ) -> ConnectorView:
        params: dict[str, Any] = {"kind": kind}
        if agent_project_id is not None:
            params["agent_project_id"] = str(agent_project_id)
        detached = await self.request(
            "DELETE", f"/v1/connectors/{connector_id}/attachments", params=params
        )
        return ConnectorView.model_validate(detached)
