from uuid import UUID

from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class SessionProjects(IdentifiableMixin, CreatedMixin, Base):
    """One row per session that belongs to a project, keyed by the session's
    id, read by that id alone. Written once: the serving logins hold SELECT
    and INSERT on it, never UPDATE or DELETE."""

    __tablename__ = "session_projects"
    project_id: Mapped[UUID]
