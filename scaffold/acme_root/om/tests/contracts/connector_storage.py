"""The connector storage contract: a tenant's connectors, one of a name,
each change conditioned on the version read, with their reviewed tools and
attachments read back whole; and each session's pin, written once. The
cases named in `CROSS_TENANT_CASES` are the tenant fence's evidence: each
one presents another tenant's identifier and asserts that nothing is found
and nothing changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.connectors.storage import ConnectorStorageInterface
from acme.om.connectors.types.connector import (
    AgentSessionConnectors,
    Connector,
    ConnectorAttachment,
    ConnectorPlace,
    ConnectorTool,
    PinnedConnector,
)
from acme.om.exceptions import PreconditionFailed, TenantMismatch, UniqueKeyTaken
from acme.om.levers.types.lever import LeverCheck, LeverFinding
from acme.om.tools.rules import definition_hash
from acme.om.tools.types.mcp import McpToolDefinition
from acme.om.tools.types.tool import Effect, ToolClass

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_connector",
        "read_connector",
        "read_connectors",
        "update_connector",
        "create_pin",
        "read_pin",
        "purge_tenant",
    }
)
"""Every method of `ConnectorStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""

LOOKUP = McpToolDefinition(
    name="lookup",
    description="Looks a word up.",
    input_schema={
        "type": "object",
        "properties": {"word": {"type": "string"}},
        "required": ["word"],
    },
    annotations={"readOnlyHint": True},
)


def make_tool() -> ConnectorTool:
    return ConnectorTool(
        definition=LOOKUP,
        definition_hash=definition_hash(LOOKUP),
        name="words__lookup",
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        findings=(LeverFinding(check=LeverCheck.UNKNOWN_NAME, detail="`define` names no tool"),),
    )


def make_connector(name: str = "words") -> Connector:
    now = utcnow()
    actor = new_id()
    return Connector(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        name=name,
        summary="Look words up.",
        place=ConnectorPlace.CLOUD,
        url="https://words.example.com/mcp",
        secret="connector-words",
    )


def reviewed(connector: Connector, agent_project_id: UUID | None = None) -> Connector:
    return connector.model_copy(
        update={
            "tools": (make_tool(),),
            "review": connector.review + 1,
            "reviewed_by": new_id(),
            "attachments": (
                ConnectorAttachment(kind="software_engineer", agent_project_id=agent_project_id),
            ),
            "version": connector.version + 1,
        }
    )


def make_pin(agent_session_id: UUID, connector: Connector) -> AgentSessionConnectors:
    return AgentSessionConnectors(
        id=agent_session_id,
        created_at=utcnow(),
        connectors=(
            PinnedConnector(
                connector_id=connector.id,
                name=connector.name,
                summary=connector.summary,
                review=1,
                place=connector.place,
                url=connector.url,
                secret=connector.secret,
                tools=(make_tool(),),
            ),
        ),
    )


class ConnectorStorageContract:
    async def test_a_connector_moves_by_its_version_and_reads_back_whole(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org = new_id()
        connector = make_connector()
        assert await storage.create_connector(org, connector, ())
        assert not await storage.create_connector(org, connector, ())
        kept = reviewed(connector, new_id())
        await storage.update_connector(org, kept, ())
        with pytest.raises(PreconditionFailed):
            await storage.update_connector(org, kept, ())
        assert await storage.read_connector(org, connector.id) == kept
        assert await storage.read_connectors(org, None, 10) == [kept]
        assert await storage.read_connectors(org, connector.id, 10) == []

    async def test_a_tenant_holds_one_connector_of_a_name(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org = new_id()
        assert await storage.create_connector(org, make_connector(), ())
        with pytest.raises(UniqueKeyTaken):
            await storage.create_connector(org, make_connector(), ())
        assert await storage.create_connector(new_id(), make_connector(), ())

    async def test_a_session_pins_once(self, storage: ConnectorStorageInterface) -> None:
        org = new_id()
        agent_session_id = new_id()
        first = make_pin(agent_session_id, make_connector())
        assert await storage.create_pin(org, first) == first
        later = AgentSessionConnectors(id=agent_session_id, created_at=utcnow(), connectors=())
        assert await storage.create_pin(org, later) == first, "the first pin stands"
        assert await storage.read_pin(org, agent_session_id) == first

    async def test_create_connector_in_another_tenant_is_not_read_here(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        connector = make_connector()
        await storage.create_connector(org_a, connector, ())
        assert not await storage.create_connector(org_b, connector, ())
        assert await storage.read_connector(org_b, connector.id) is None

    async def test_read_connector_of_another_tenant_finds_nothing(
        self, storage: ConnectorStorageInterface
    ) -> None:
        connector = make_connector()
        await storage.create_connector(new_id(), connector, ())
        assert await storage.read_connector(new_id(), connector.id) is None

    async def test_read_connectors_of_another_tenant_finds_nothing(
        self, storage: ConnectorStorageInterface
    ) -> None:
        await storage.create_connector(new_id(), make_connector(), ())
        assert await storage.read_connectors(new_id(), None, 10) == []

    async def test_update_connector_of_another_tenant_changes_nothing(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org = new_id()
        connector = make_connector()
        await storage.create_connector(org, connector, ())
        with pytest.raises((PreconditionFailed, TenantMismatch)):
            await storage.update_connector(new_id(), reviewed(connector), ())
        assert await storage.read_connector(org, connector.id) == connector

    async def test_create_pin_in_another_tenant_is_not_read_here(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        pin = make_pin(new_id(), make_connector())
        await storage.create_pin(org_a, pin)
        with pytest.raises(TenantMismatch):
            await storage.create_pin(org_b, pin)
        assert await storage.read_pin(org_b, pin.id) is None
        assert await storage.read_pin(org_a, pin.id) == pin

    async def test_read_pin_of_another_tenant_finds_nothing(
        self, storage: ConnectorStorageInterface
    ) -> None:
        pin = make_pin(new_id(), make_connector())
        await storage.create_pin(new_id(), pin)
        assert await storage.read_pin(new_id(), pin.id) is None

    async def test_purge_tenant_takes_only_that_tenants_rows(
        self, storage: ConnectorStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        kept = make_connector()
        gone = make_connector()
        await storage.create_connector(org_a, kept, ())
        await storage.create_connector(org_b, gone, ())
        await storage.create_pin(org_a, make_pin(new_id(), kept))
        session_b = new_id()
        await storage.create_pin(org_b, make_pin(session_b, gone))
        assert await storage.purge_tenant(org_b, 100) == 2
        assert await storage.read_connector(org_b, gone.id) is None
        assert await storage.read_pin(org_b, session_b) is None
        assert await storage.read_connector(org_a, kept.id) == kept
        assert await storage.purge_tenant(org_b, 100) == 0
