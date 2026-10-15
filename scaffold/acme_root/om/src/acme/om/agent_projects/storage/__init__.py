"""Storage of the agent projects swimlane: each tenant's agent projects, and the agent project
each session belongs to. Every operation takes org_id first.

An agent project's name may change and the agent project may go while no session
belongs to it; its repository never moves. A session's row is written once
and never rewritten: the serving logins hold SELECT and INSERT on its table alone,
and the purge login deletes it with its session or its tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_projects.types.agent_project import AgentProject
from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.outbox.types.row import OutboxRow


class AgentProjectStorageInterface(ABC):
    @abstractmethod
    async def create_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The agent project, with the rows that announce it. False, with nothing
        landed, when its id is written already."""
        ...

    @abstractmethod
    async def read_agent_project(
        self, org_id: UUID, agent_project_id: UUID
    ) -> AgentProject | None: ...

    @abstractmethod
    async def read_agent_projects(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[AgentProject]:
        """The tenant's agent projects by id, strictly after `after`."""
        ...

    @abstractmethod
    async def write_agent_project(
        self, org_id: UUID, agent_project: AgentProject, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A stored agent project as changed, with the rows that announce it, in one
        commit. False, with nothing landed, when the tenant holds no such
        agent project: a write never brings a removed one back."""
        ...

    @abstractmethod
    async def delete_agent_project(
        self, org_id: UUID, agent_project_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The agent project, gone with the rows that announce it, in one statement
        that also asks that no session's row names it. False, with nothing
        landed, when the agent project is not the tenant's or a session belongs to
        it."""
        ...

    @abstractmethod
    async def bind_session(self, org_id: UUID, binding: SessionAgentProject) -> SessionAgentProject:
        """The session's row, written once: `binding` lands when the session
        has none, and the stored one is answered either way. A session id
        another tenant holds a row for is `TenantMismatch`."""
        ...

    @abstractmethod
    async def read_binding(
        self, org_id: UUID, agent_session_id: UUID
    ) -> SessionAgentProject | None: ...

    @abstractmethod
    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID) -> bool:
        """The row of a session its purge has claimed, under the purge login.
        False when none was left."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of a deleted tenant past its retention, its
        sessions' rows before its agent projects; returns how many."""
        ...
