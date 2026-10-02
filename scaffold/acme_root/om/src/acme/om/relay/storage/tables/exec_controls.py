from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ExecControls(IdentifiableMixin, TrackableMixin, Base):
    """What each host's control stream carried about the items it held. A
    host's are read in the order they were made, and a session's go with
    it; org_id leads both indexes, so it gets none of its own."""

    __tablename__ = "exec_controls"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_exec_controls_org_id_host_id_created_at", "org_id", "host_id", "created_at"),
        Index("ix_exec_controls_org_id_session_id", "org_id", "session_id"),
    )
    session_id: Mapped[UUID]
    item_id: Mapped[UUID]
    host_id: Mapped[UUID]
    kind: Mapped[str]
