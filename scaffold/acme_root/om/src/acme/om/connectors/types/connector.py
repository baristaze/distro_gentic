"""A connector: a tenant's MCP server, the tools of it a person reviewed,
and the kinds it is attached to as a toolset.

A connector on the internet is called from the platform's cloud, at its
address, with a credential the platform keeps as the tenant's secret. One
inside the tenant's wall runs on the tenant's own host, which its owner
configures by name, and is reached through `exec` work: the platform names
it and never opens a connection to it, and never holds its credential."""

from enum import StrEnum
from typing import ClassVar, Literal, Self, get_args
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.base import Created, Identifiable, Platform, Trackable
from acme.om.levers.types.lever import LeverFinding
from acme.om.tools.types.mcp import McpToolDefinition
from acme.om.tools.types.tool import TOOL_NAME, Effect, ToolClass
from acme.om.tools.types.toolset import SUMMARY_CHARS

CONNECTOR_NAME = r"^[a-z][a-z0-9_]{0,23}$"
"""A connector's name, which is its toolset's and begins each of its tools'
names: short, so a tool's name stays within the registry's."""

HOST_SERVER = r"^[a-z][a-z0-9_-]{0,63}$"
"""The name a host's owner gives a server it runs."""

HEADER_NAME = r"^[A-Za-z0-9-]{1,64}$"

MAX_TOOLS = 64
"""The most tools of one server a person binds: a toolset loads whole, and
a model chooses worse among many."""

ServerToolClass = Literal[ToolClass.READ, ToolClass.INTEGRATION, ToolClass.DESTRUCTIVE]
"""The classes a server's tool may take: it reads a system, acts on it, or
changes it past undoing. Policy keys on the class, as on every tool's."""

TOOL_CLASSES: frozenset[ToolClass] = frozenset(get_args(ServerToolClass))


class ConnectorPlace(StrEnum):
    """Where a connector's server runs, and so where its calls are made."""

    CLOUD = "cloud"  # on the internet, called from the platform's cloud
    HOST = "host"  # inside the tenant's wall, run by the tenant's host


class ConnectorTool(Platform):
    """One tool of the server a person reviewed: its definition as the server
    listed it, pinned by `definition_hash`; the name a session calls it by;
    the class and the effect the person gave it, since what a server says
    of its own tool is a hint and never authority; and what the lever
    checks found in its description."""

    definition: McpToolDefinition
    definition_hash: str = Field(min_length=1)
    name: str = Field(pattern=TOOL_NAME)
    authorization_class: ToolClass = ToolClass.INTEGRATION
    effect: Effect = Effect.UNSAFE
    findings: tuple[LeverFinding, ...] = ()

    @model_validator(mode="after")
    def _a_server_tools_class(self) -> Self:
        if self.authorization_class not in TOOL_CLASSES:
            classes = ", ".join(sorted(c.value for c in TOOL_CLASSES))
            raise ValueError(f"a server's tool is of the class {classes}")
        return self


class ConnectorAttachment(Platform):
    """A kind a connector is attached to, for one project's sessions or, with
    none, for every session of the tenant. A deferred one waits for the
    agent to load it; one that is not is in its registry from the start."""

    kind: str = Field(min_length=1, max_length=64)
    project_id: UUID | None = None
    deferred: bool = True


class Connector(Identifiable, Trackable):
    """A tenant's server. `name` is its toolset's, and `summary` the line
    `load_toolset` gives it. A cloud connector has its `url`, and its
    credential goes in `credential_header`, after `credential_scheme`; the
    credential itself is the tenant's secret `secret` names, never a value.
    A host connector names the server its host's owner configures,
    `host_server`. `tools` is what a person last reviewed, at review
    `review`, which is its toolset's version: none until a person reviews
    it. `version` is the row's, which each write moves."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = (
        "secret",
        "tools",
        "review",
        "reviewed_by",
        "attachments",
        "version",
    )

    name: str = Field(pattern=CONNECTOR_NAME)
    summary: str = Field(min_length=1, max_length=SUMMARY_CHARS)
    place: ConnectorPlace
    url: str | None = Field(default=None, max_length=2_000)
    credential_header: str = Field(default="Authorization", pattern=HEADER_NAME)
    credential_scheme: str = Field(default="Bearer", max_length=32)
    secret: str | None = Field(default=None, max_length=200)
    host_server: str | None = Field(default=None, pattern=HOST_SERVER)
    tools: tuple[ConnectorTool, ...] = Field(default=(), max_length=MAX_TOOLS)
    review: int = Field(default=0, ge=0)
    reviewed_by: UUID | None = None
    attachments: tuple[ConnectorAttachment, ...] = ()
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _one_address(self) -> Self:
        if "\n" in self.summary or "\r" in self.summary:
            raise ValueError("a connector's summary is one line")
        if (self.place is ConnectorPlace.CLOUD) != (self.url is not None):
            raise ValueError("a cloud connector, and only one, has an address")
        if (self.place is ConnectorPlace.HOST) != (self.host_server is not None):
            raise ValueError("a host connector, and only one, names its host's server")
        if self.place is ConnectorPlace.HOST and self.secret is not None:
            raise ValueError("a host connector's credential stays on its host")
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("a connector names each of its tools once")
        return self


class PinnedConnector(Platform):
    """A connector as a session holds it, at the review it pinned: what its
    toolset renders and how its calls reach the server, kept whole so a
    later review or attachment never moves a session's tool definitions."""

    connector_id: UUID
    name: str = Field(pattern=CONNECTOR_NAME)
    summary: str = Field(min_length=1, max_length=SUMMARY_CHARS)
    review: int = Field(ge=1)
    place: ConnectorPlace
    url: str | None = None
    credential_header: str = "Authorization"
    credential_scheme: str = "Bearer"
    secret: str | None = None
    host_server: str | None = None
    tools: tuple[ConnectorTool, ...] = Field(min_length=1)
    deferred: bool = True


class AgentSessionConnectors(Identifiable, Created):
    """The connectors one session holds, pinned as its first run began: the
    row's id is the session's, so a session pins once."""

    connectors: tuple[PinnedConnector, ...] = ()


class ConnectorDraft(Platform):
    """What a person connects: a cloud server's address, or the name of the
    server the tenant's host runs, never both."""

    name: str = Field(pattern=CONNECTOR_NAME)
    summary: str = Field(min_length=1, max_length=SUMMARY_CHARS)
    url: str | None = Field(default=None, max_length=2_000)
    credential_header: str = Field(default="Authorization", pattern=HEADER_NAME)
    credential_scheme: str = Field(default="Bearer", max_length=32)
    host_server: str | None = Field(default=None, pattern=HOST_SERVER)

    @model_validator(mode="after")
    def _one_place(self) -> Self:
        if "\n" in self.summary or "\r" in self.summary:
            raise ValueError("a connector's summary is one line")
        if (self.url is None) == (self.host_server is None):
            raise ValueError("a connector has an address, or names its host's server")
        return self

    @property
    def place(self) -> ConnectorPlace:
        return ConnectorPlace.CLOUD if self.url is not None else ConnectorPlace.HOST


class ReviewedTool(Platform):
    """One tool a person binds: the server's tool, the hash of the
    definition they read, and the class and the effect they give it."""

    server_tool: str = Field(min_length=1, max_length=128)
    definition_hash: str = Field(min_length=1, max_length=80)
    authorization_class: ToolClass = ToolClass.INTEGRATION
    effect: Effect = Effect.UNSAFE


class ConnectorReview(Platform):
    """A person's review: every tool they bind, none to withdraw them all.
    A host connector's review carries the definitions as its host listed
    them, since the platform never reaches into the wall to list them."""

    tools: tuple[ReviewedTool, ...] = Field(default=(), max_length=MAX_TOOLS)
    definitions: tuple[McpToolDefinition, ...] | None = Field(default=None, max_length=1_000)


class ListedTool(Platform):
    """A tool as the server lists it now, with the hash a review names it
    by and what the lever checks find in its description."""

    definition: McpToolDefinition
    definition_hash: str
    findings: tuple[LeverFinding, ...] = ()
