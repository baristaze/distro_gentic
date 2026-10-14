from uuid import UUID

from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AgentSessionProjects(IdentifiableMixin, CreatedMixin, Base):
    """One row per session that belongs to an agent project, keyed by the session's
    id, read by that id alone. Written once: the serving logins hold SELECT
    and INSERT on it, never UPDATE or DELETE."""

    __tablename__ = "agent_session_projects"
    agent_project_id: Mapped[UUID]
