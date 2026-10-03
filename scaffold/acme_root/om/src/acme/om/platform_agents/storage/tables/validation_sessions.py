from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ValidationSessions(IdentifiableMixin, TrackableMixin, Base):
    """A delivery's check run with no agent: its project, the check, the
    commit it runs at and the one its checks come from, and the execution
    record of its run once it is recorded. Read by its id alone."""

    __tablename__ = "validation_sessions"
    # The columns the previous release wrote: they leave the mapping a
    # release before they leave the table (ADR 0038).
    __table_args__ = (
        Column("lab_id", Uuid()),
        Column("check_version", Text()),
        Column("parameters", JSONB()),
    )
    __mapper_args__ = {"exclude_properties": ["lab_id", "check_version", "parameters"]}
    # Null only in a row the previous release wrote: the model holds every
    # one, and they turn not null with the drop.
    project_id: Mapped[UUID | None]
    check_name: Mapped[str]
    head: Mapped[str | None]
    base: Mapped[str | None]
    status: Mapped[str]
    run_id: Mapped[UUID | None]
    finished_at: Mapped[datetime | None]
    version: Mapped[int]
