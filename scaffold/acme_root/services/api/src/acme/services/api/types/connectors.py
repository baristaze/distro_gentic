"""Wire types of a tenant's connectors: a server a person connects, what
it lists for a review, a person's review of its tools, and a kind it is
attached to. A credential goes in and never comes back."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, SecretStr

from acme.om.connectors.types.connector import (
    CONNECTOR_NAME,
    HEADER_NAME,
    HOST_SERVER,
    MAX_TOOLS,
    ConnectorPlace,
)
from acme.om.tools.types.tool import Effect, ToolClass
from acme.om.tools.types.toolset import SUMMARY_CHARS
from acme.services.api.types.common import RequestBody, View
from acme.services.api.types.levers import FindingView

MAX_CREDENTIAL = 4_096


class ConnectRequest(RequestBody):
    """A server on the internet, at its `url`, with the credential its calls
    carry in `credential_header`, after `credential_scheme`; or the server
    the tenant's host runs, by the name its owner gives it,
    `host_server`, whose credential stays on that host."""

    name: str = Field(pattern=CONNECTOR_NAME)
    summary: str = Field(min_length=1, max_length=SUMMARY_CHARS)
    url: str | None = Field(default=None, max_length=2_000)
    credential_header: str = Field(default="Authorization", pattern=HEADER_NAME)
    credential_scheme: str = Field(default="Bearer", max_length=32)
    credential: SecretStr | None = Field(default=None, min_length=1, max_length=MAX_CREDENTIAL)
    host_server: str | None = Field(default=None, pattern=HOST_SERVER)


class DefinitionBody(RequestBody):
    """A tool as a server lists it: its name, its description, its input
    schema, and its annotations, as written."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10_000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)


class ReviewedToolBody(RequestBody):
    """A tool a person binds: the server's tool, the hash of the definition
    they read, and the class and the effect they give it, each said
    outright: what a server says of its own tool is a hint, never
    authority. A class that acts on the server's system waits for a person
    at each call, as any outward call does."""

    server_tool: str = Field(min_length=1, max_length=128)
    definition_hash: str = Field(min_length=1, max_length=80)
    authorization_class: ToolClass
    effect: Effect


class ConnectorReviewRequest(RequestBody):
    """Every tool a person binds, none to withdraw them all. A host server's
    review carries the definitions its host lists."""

    tools: list[ReviewedToolBody] = Field(default_factory=list, max_length=MAX_TOOLS)
    definitions: list[DefinitionBody] | None = Field(default=None, max_length=1_000)


class AttachRequest(RequestBody):
    """A kind the connector joins, for one project's sessions or every
    session of the tenant, deferred until the agent loads it unless
    `deferred` is false."""

    kind: str = Field(min_length=1, max_length=64)
    project_id: UUID | None = None
    deferred: bool = True


class ListedToolView(View):
    """A tool as the server lists it now, the hash a review names it by, and
    what the lever checks find in its description."""

    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any]
    definition_hash: str
    findings: list[FindingView]


class ConnectorToolView(View):
    """A tool a person reviewed: the name a session calls it by, the
    server's tool and the definition read, its class and its effect, and
    what the lever checks found in its description."""

    name: str
    server_tool: str
    description: str
    input_schema: dict[str, Any]
    definition_hash: str
    authorization_class: ToolClass
    effect: Effect
    findings: list[FindingView]


class AttachmentView(View):
    kind: str
    project_id: UUID | None
    deferred: bool


class ConnectorView(View):
    """A connector: where its server runs, its address or its host's server,
    whether its calls carry a credential, never the credential; the tools
    a person reviewed at review `review`, its toolset's version; the kinds
    it is attached to; and `version`, which each write moves."""

    id: UUID
    name: str
    summary: str
    place: ConnectorPlace
    url: str | None
    credential_header: str
    credential_scheme: str
    has_credential: bool
    host_server: str | None
    tools: list[ConnectorToolView]
    review: int
    reviewed_by: UUID | None
    attachments: list[AttachmentView]
    version: int
    created_at: datetime
    updated_at: datetime
