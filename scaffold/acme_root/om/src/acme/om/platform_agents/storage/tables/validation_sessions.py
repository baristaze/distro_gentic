from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ValidationSessions(IdentifiableMixin, TrackableMixin, Base):
    """A delivery's check run with no agent: its project, the check, the
    commit it runs at and the one its checks come from, and the execution
    record of its run once it is recorded, or why it was refused. Read by
    its id alone."""

    __tablename__ = "validation_sessions"
    project_id: Mapped[UUID]
    check_name: Mapped[str]
    head: Mapped[str]
    base: Mapped[str]
    status: Mapped[str]
    run_id: Mapped[UUID | None]
    finished_at: Mapped[datetime | None]
    refusal: Mapped[str | None]
    version: Mapped[int]
