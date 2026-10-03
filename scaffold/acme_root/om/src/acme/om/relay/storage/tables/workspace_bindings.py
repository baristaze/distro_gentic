from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class WorkspaceBindings(IdentifiableMixin, TrackableMixin, Base):
    """The host that holds each session's workspace, or an instance a run
    made for one (`instance_of`): one row a session or an instance, which
    the unique index org_id leads holds, so it gets no index of its own."""

    __tablename__ = "workspace_bindings"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_workspace_bindings_org_id_session_id", "org_id", "session_id", unique=True),
    )
    session_id: Mapped[UUID]
    host_id: Mapped[UUID]
    host_name: Mapped[str]
    location: Mapped[str]
    instance_of: Mapped[UUID | None]
    version: Mapped[int]
