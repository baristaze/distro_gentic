"""The connectors' pure rules: the name a server's tool is called by, the
addresses the platform's cloud may call, what a review binds, and what a
session pins of its tenant's connectors."""

import ipaddress
import re
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from acme.integrations.mcp import McpHttp, McpServer
from acme.om.connectors.types.connector import (
    Connector,
    ConnectorPlace,
    ConnectorReview,
    ConnectorTool,
    ListedTool,
    PinnedConnector,
    SessionConnectors,
)
from acme.om.exceptions import ValidationFailed
from acme.om.levers.rules import checked
from acme.om.levers.types.lever import LeverFinding, LeverReach
from acme.om.tools.rules import definition_hash
from acme.om.tools.types.mcp import McpToolDefinition
from acme.om.tools.types.tool import TOOL_NAME
from acme.om.tools.types.toolset import Toolset

SEPARATOR = "__"
"""Between a connector's name and its tool's in the name a session calls
the tool by, so no tool of a server takes a name the platform's tools
hold."""

LOOPBACK = frozenset({"localhost"})


def tool_name(connector: str, server_tool: str) -> str | None:
    """The name a session calls a server's tool by: the connector's name, the
    separator, and the tool's own name in lower case with every other
    character an underscore. None when it does not fit a tool's name."""
    own = re.sub(r"[^a-z0-9_]", "_", server_tool.lower())
    name = f"{connector}{SEPARATOR}{own}"
    return name if re.fullmatch(TOOL_NAME, name) else None


def address_refusal(url: str, *, private: bool) -> str | None:
    """Why the platform's cloud may not call `url`, or None when it may. An
    address is an http or https URL with no credential in it. Unless
    `private` (a local stack, whose servers run beside it), it is https,
    and its host is a name or a public address: never this host, a
    private network, or a link-local one, so a tenant's address never
    reaches what stands beside the platform. A name is resolved and held
    to the same at each exchange (`impl.addresses`)."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "a connector's address is an http or https URL"
    if parts.username or parts.password:
        return "a connector's address carries no credential"
    if private:
        return None
    if parts.scheme != "https":
        return "a connector's address is https"
    host = parts.hostname
    if host in LOOPBACK or host.endswith(".localhost"):
        return "a connector's address is never this host"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    return None if public(address) else f"{host} is not a public address"


def public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address is one the internet routes to: not this host, a
    private or a link-local network, or one reserved."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return public(address.ipv4_mapped)
    return address.is_global and not address.is_multicast


def findings_of(definition: McpToolDefinition, reach: LeverReach) -> tuple[LeverFinding, ...]:
    """What the lever checks find in a tool's description, as they read a
    playbook's text: a model reads it to choose the tool. The tools of its
    own server are among those it may name."""
    return checked(definition.description, reach) if definition.description.strip() else ()


def reach_with(
    reach: LeverReach, listed: Iterable[McpToolDefinition], connector: str
) -> LeverReach:
    """`reach` with a server's own tools, by the server's names and by the
    names a session calls them by, which its descriptions may name."""
    own = {tool.name for tool in listed}
    called = {name for name in (tool_name(connector, each) for each in own) if name is not None}
    return LeverReach(tools=reach.tools | own | called, kinds=reach.kinds)


def listed_tools(listing: Sequence[McpToolDefinition], reach: LeverReach) -> tuple[ListedTool, ...]:
    """A server's listing as a person reads it before a review: each tool,
    the hash a review names it by, and what the lever checks find."""
    return tuple(
        ListedTool(
            definition=definition,
            definition_hash=definition_hash(definition),
            findings=findings_of(definition, reach),
        )
        for definition in listing
    )


def reviewed(
    connector: Connector,
    listing: Sequence[McpToolDefinition],
    review: ConnectorReview,
    reach: LeverReach,
    taken: Iterable[str],
) -> tuple[ConnectorTool, ...]:
    """The tools a review binds, each at the definition the server lists now
    and the person read: `ValidationFailed`, naming every reason, when a
    named tool is not listed, is listed at another hash, is named twice,
    or takes a name the platform's tools hold or that does not fit."""
    by_name: dict[str, McpToolDefinition] = {}
    for definition in listing:
        if definition.name in by_name:
            raise ValidationFailed(f"the server lists {definition.name!r} twice")
        by_name[definition.name] = definition
    held = frozenset(taken)
    reasons: list[str] = []
    bound: list[ConnectorTool] = []
    names: set[str] = set()
    wide = reach_with(reach, by_name.values(), connector.name)
    for each in review.tools:
        definition = by_name.get(each.server_tool)
        if definition is None:
            reasons.append(f"the server lists no tool {each.server_tool!r}")
            continue
        found = definition_hash(definition)
        if found != each.definition_hash:
            reasons.append(
                f"{each.server_tool} hashes to {found}, not the {each.definition_hash} reviewed"
            )
            continue
        name = tool_name(connector.name, each.server_tool)
        if name is None:
            reasons.append(f"{each.server_tool} makes no tool name under {connector.name}")
            continue
        if name in names or name in held:
            reasons.append(f"{each.server_tool} takes the name {name}, which is held")
            continue
        names.add(name)
        bound.append(
            ConnectorTool(
                definition=definition,
                definition_hash=found,
                name=name,
                authorization_class=each.authorization_class,
                effect=each.effect,
                findings=findings_of(definition, wide),
            )
        )
    if reasons:
        raise ValidationFailed("; ".join(reasons))
    return tuple(sorted(bound, key=lambda tool: tool.name))


def attached_to(connector: Connector, kind: str, project_id: UUID | None) -> tuple[bool, bool]:
    """Whether a connector is attached to a session of `kind` in
    `project_id`, by the tenant or by the session's project, and whether
    it waits for a load there: deferred unless an attachment that reaches
    the session holds it from the start."""
    reaching = [
        each
        for each in connector.attachments
        if each.kind == kind and each.project_id in (None, project_id)
    ]
    return bool(reaching), all(each.deferred for each in reaching)


def pinned(
    connectors: Iterable[Connector],
    kind: str,
    project_id: UUID | None,
    *,
    inside_wall: bool,
    parent: SessionConnectors | None,
    child: bool,
) -> tuple[PinnedConnector, ...]:
    """What a session of `kind` in `project_id` pins of its tenant's
    connectors: each attached to its kind for it, reviewed, and run on
    its side of the wall (a host connector inside it, a cloud one outside),
    by name. A sub-agent pins only what its parent pinned too, at the same
    review, so it never holds a tool its parent does not."""
    place = ConnectorPlace.HOST if inside_wall else ConnectorPlace.CLOUD
    parents: Mapping[UUID, PinnedConnector] = (
        {} if parent is None else {each.connector_id: each for each in parent.connectors}
    )
    held: list[PinnedConnector] = []
    for connector in connectors:
        reaches, deferred = attached_to(connector, kind, project_id)
        if not reaches or not connector.tools or connector.place is not place:
            continue
        if child:
            above = parents.get(connector.id)
            if above is None or above.review != connector.review:
                continue
        held.append(
            PinnedConnector(
                connector_id=connector.id,
                name=connector.name,
                summary=connector.summary,
                review=connector.review,
                place=connector.place,
                url=connector.url,
                credential_header=connector.credential_header,
                credential_scheme=connector.credential_scheme,
                secret=connector.secret,
                host_server=connector.host_server,
                tools=connector.tools,
                deferred=deferred,
            )
        )
    return tuple(sorted(held, key=lambda each: each.name))


def cloud_server(connector: Connector | PinnedConnector) -> McpServer:
    """The server a cloud connector names, as the MCP client reaches it: at
    its address, its credential, the tenant's secret it names, in its
    header."""
    return McpServer(
        name=connector.name,
        transport=McpHttp(
            url=connector.url or "",
            credential_header=connector.credential_header,
            credential_scheme=connector.credential_scheme,
        ),
        secret=connector.secret,
    )


def toolset_of(connector: PinnedConnector) -> Toolset:
    """The toolset a pinned connector renders: its name, its review as its
    version, its summary, and its tools."""
    return Toolset(
        name=connector.name,
        version=connector.review,
        summary=connector.summary,
        tools=tuple(tool.name for tool in connector.tools),
    )


def still_reviewed(connector: Connector | None, pinned_tool: ConnectorTool) -> str | None:
    """Why a session's pinned tool is no longer served, or None when it is: the
    connector is gone, or no tool of its current review is the one pinned,
    at the same definition, class, and effect. A person who withdraws a
    tool, or reviews it again at another definition, class, or effect,
    stops its calls in every session that pinned it, at their next call:
    the session holds the class and the effect that decide whether a call
    waits for a person, so a stricter review never reaches it as the
    looser one."""
    if connector is None:
        return f"{pinned_tool.name}: its connector is gone"
    for tool in connector.tools:
        if tool.name == pinned_tool.name and tool.definition_hash == pinned_tool.definition_hash:
            if (
                tool.authorization_class == pinned_tool.authorization_class
                and tool.effect == pinned_tool.effect
            ):
                return None
            return (
                f"{pinned_tool.name}: {connector.name} reviewed it again as "
                f"{tool.authorization_class.value} and {tool.effect.value}; this session "
                f"holds it as {pinned_tool.authorization_class.value} and "
                f"{pinned_tool.effect.value}"
            )
    return (
        f"{pinned_tool.name}: no review of {connector.name} serves it at the definition "
        "this session holds"
    )
