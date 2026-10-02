from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class SessionPlacements(IdentifiableMixin, TrackableMixin, Base):
    """Where each placed session runs: one row a session, which the unique
    index org_id leads holds, so it gets no index of its own."""

    __tablename__ = "session_placements"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_session_placements_org_id_session_id", "org_id", "session_id", unique=True),
    )
    session_id: Mapped[UUID]
    pool_id: Mapped[UUID | None]
    version: Mapped[int]
