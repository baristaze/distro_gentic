"""The MCP servers this host runs inside its wall, for the tenants'
connectors. An `exec` item names a server and one of its tools; the host
starts the server its owner configures under that name, with a credential
from its own secret store, lists its tools, and calls the tool only when
the server lists it as the definition a person reviewed. The platform
names the server and sends the call; it never opens a connection to the
server, and never holds its credential.

Each call is one exchange through the engine's MCP client: the server's
process starts for the call and stops with it, by the item's deadline,
and everything it sends back is redacted of the credential."""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr

from acme.apps.host.ceilings import HostServer
from acme.client.types import ExecDetailView
from acme.infra.exceptions import InfraException
from acme.infra.secrets import SecretsInterface
from acme.integrations.mcp import McpAnswer, McpClientInterface, McpListedTool, McpServer, McpStdio
from acme.integrations.mcp.sdk import McpClientSdkImpl


class NoSuchServer(InfraException):
    """A server this host's owner does not name: the item is refused, and
    nothing starts."""

    http_status = 403
    code = "refused_by_host"


class HostServers:
    """The servers `servers` names, as the owner's ceilings name them,
    reached through `client`, each credential read from `secrets` under
    the host's own tenant."""

    def __init__(
        self,
        servers: Mapping[str, HostServer],
        secrets: SecretsInterface,
        client: McpClientInterface | None = None,
    ) -> None:
        self._servers = servers
        self._secrets = secrets
        self._client = client or McpClientSdkImpl()

    def credential_of(self, name: str) -> str | None:
        """The name of the secret a server's calls carry, for the audit."""
        server = self._servers.get(name)
        return None if server is None else server.credential

    async def call(self, detail: ExecDetailView) -> McpAnswer:
        """The item's call, on a connection of its own, by its deadline.
        `NoSuchServer` for a server the owner does not name; `McpToolRefused`
        for a tool the server does not list as the definition sent, which
        is never called."""
        request = detail.request
        name = str(request.get("server", ""))
        tool = str(request.get("tool", ""))
        configured = self._servers.get(name)
        if configured is None:
            raise NoSuchServer(f"this host runs no MCP server named {name!r}")
        server = McpServer(
            name=name,
            transport=McpStdio(
                command=configured.command,
                args=configured.args,
                env=configured.env,
                cwd=configured.cwd,
                credential_env=configured.credential_env,
            ),
            secret=configured.credential,
        )
        credential = (
            None
            if configured.credential is None
            else SecretStr(
                await self._secrets.get(
                    detail.org_id, configured.credential, deadline=detail.deadline
                )
            )
        )
        reviewed = _canonical(request.get("definition", {}))

        def refuse(listed: McpListedTool | None) -> str | None:
            if listed is None:
                return f"{name} lists no tool {tool!r}"
            if _canonical(listed.model_dump(mode="json")) != reviewed:
                return (
                    f"{name}/{tool} is not the definition a person reviewed: its definition "
                    "changed, and it is not served until someone reviews it again"
                )
            return None

        arguments = request.get("arguments", {})
        return await self._client.call_tool(
            server,
            credential,
            tool,
            arguments if isinstance(arguments, Mapping) else {},
            key=detail.call_id,
            refuse=refuse,
            deadline=detail.deadline,
        )


def _canonical(definition: Any) -> str:
    """A definition as a pin reads it: its JSON, keys sorted."""
    return json.dumps(definition, sort_keys=True, separators=(",", ":"))
