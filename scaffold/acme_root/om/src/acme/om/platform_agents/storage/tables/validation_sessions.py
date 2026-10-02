from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ValidationSessions(IdentifiableMixin, TrackableMixin, Base):
    """A check run on a station with no agent: what the lab's daemon runs,
    and the execution record of its run once it is recorded. Read by its id
    alone."""

    __tablename__ = "validation_sessions"
    lab_id: Mapped[UUID]
    check_name: Mapped[str]
    check_version: Mapped[str]
    parameters: Mapped[dict[str, Any]]
    status: Mapped[str]
    run_id: Mapped[UUID | None]
    finished_at: Mapped[datetime | None]
    version: Mapped[int]
