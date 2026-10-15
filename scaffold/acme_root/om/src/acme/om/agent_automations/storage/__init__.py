"""Storage of the agent automations swimlane: the tenant's agent automations, and the
record of every firing. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.agent_automations.types.agent_automation import (
    AgentAutomation,
    AgentAutomationPrincipal,
    AgentAutomationRun,
    Limits,
)
from acme.om.outbox.types.row import OutboxRow


class AgentAutomationStorageInterface(ABC):
    @abstractmethod
    async def create_agent_automation(
        self, org_id: UUID, agent_automation: AgentAutomation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already."""
        ...

    @abstractmethod
    async def read_agent_automation(
        self, org_id: UUID, agent_automation_id: UUID
    ) -> AgentAutomation | None: ...

    @abstractmethod
    async def write_agent_automation(
        self, org_id: UUID, agent_automation: AgentAutomation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A stored agent automation as changed, with the rows that announce it, in
        one commit. False, with nothing landed, when the tenant holds no such
        agent automation."""
        ...

    @abstractmethod
    async def read_agent_automations(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[AgentAutomation]:
        """The tenant's agent automations by id, strictly after `after`."""
        ...

    @abstractmethod
    async def admit(
        self, org_id: UUID, run: AgentAutomationRun, limits: Limits, now: datetime
    ) -> AgentAutomationRun:
        """A run asking to start at `now`, written as its limits leave it
        (`agent_automations.rules.admitted`), with what its agent automation's runs hold
        in the period that ends now, and how many others wait in its queue,
        read in the same write, which no other admission of the agent automation
        shares. A run written already as queued is written over; one written
        otherwise answers as stored."""
        ...

    @abstractmethod
    async def create_run(self, org_id: UUID, run: AgentAutomationRun) -> AgentAutomationRun:
        """A run that asks no limit, such as a refusal; one written already
        answers as stored."""
        ...

    @abstractmethod
    async def write_run(self, org_id: UUID, run: AgentAutomationRun) -> None:
        """A run's change after it was admitted: its session, its budget, its
        close, or a queued run refused."""
        ...

    @abstractmethod
    async def read_run(self, org_id: UUID, run_id: UUID) -> AgentAutomationRun | None: ...

    @abstractmethod
    async def write_principal(
        self, org_id: UUID, principal: AgentAutomationPrincipal
    ) -> AgentAutomationPrincipal:
        """The tenant's agent automation principal granted: the one row of the
        tenant, its role and its granter written over when it stands, its
        id kept. Answers the row as stored."""
        ...

    @abstractmethod
    async def read_principal(self, org_id: UUID) -> AgentAutomationPrincipal | None: ...

    @abstractmethod
    async def read_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        """The agent automation's runs, newest first."""
        ...

    @abstractmethod
    async def read_open_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        """Its started runs not yet closed, oldest first."""
        ...

    @abstractmethod
    async def read_queued_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        """Its queued runs, oldest first."""
        ...

    @abstractmethod
    async def read_session_run(
        self, org_id: UUID, agent_session_id: UUID
    ) -> AgentAutomationRun | None:
        """The latest started run that names the session."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention, its agent automation principal among them; returns how many
        went."""
        ...
