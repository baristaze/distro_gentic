"""Storage of the projects swimlane: each tenant's projects, and the project
each session belongs to. Every operation takes org_id first.

A project's name may change and the project may go while no session
belongs to it; its repository never moves. A session's row is written once
and never rewritten: the serving logins hold SELECT and INSERT on its table alone,
and the purge login deletes it with its session or its tenant."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.outbox.types.row import OutboxRow
from acme.om.projects.types.binding import SessionProject
from acme.om.projects.types.project import Project


class ProjectStorageInterface(ABC):
    @abstractmethod
    async def create_project(
        self, org_id: UUID, project: Project, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The project, with the rows that announce it. False, with nothing
        landed, when its id is written already."""
        ...

    @abstractmethod
    async def read_project(self, org_id: UUID, project_id: UUID) -> Project | None: ...

    @abstractmethod
    async def read_projects(self, org_id: UUID, after: UUID | None, limit: int) -> list[Project]:
        """The tenant's projects by id, strictly after `after`."""
        ...

    @abstractmethod
    async def write_project(
        self, org_id: UUID, project: Project, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A stored project as changed, with the rows that announce it, in one
        commit. False, with nothing landed, when the tenant holds no such
        project: a write never brings a removed one back."""
        ...

    @abstractmethod
    async def delete_project(
        self, org_id: UUID, project_id: UUID, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The project, gone with the rows that announce it, in one statement
        that also asks that no session's row names it. False, with nothing
        landed, when the project is not the tenant's or a session belongs to
        it."""
        ...

    @abstractmethod
    async def bind_session(self, org_id: UUID, binding: SessionProject) -> SessionProject:
        """The session's row, written once: `binding` lands when the session
        has none, and the stored one is answered either way. A session id
        another tenant holds a row for is `TenantMismatch`."""
        ...

    @abstractmethod
    async def read_binding(self, org_id: UUID, session_id: UUID) -> SessionProject | None: ...

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID) -> bool:
        """The row of a session its purge has claimed, under the purge login.
        False when none was left."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of a deleted tenant past its retention, its
        sessions' rows before its projects; returns how many."""
        ...
