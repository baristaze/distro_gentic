from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AutomationRuns(IdentifiableMixin, CreatedMixin, Base):
    """The record of every firing. An automation's runs are read by its id
    and their time, and the run of a session by the session, which the two
    indexes serve; both lead with org_id, so it gets no index of its own."""

    __tablename__ = "automation_runs"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "ix_automation_runs_org_id_automation_id_created_at",
            "org_id",
            "automation_id",
            "created_at",
        ),
        Index("ix_automation_runs_org_id_session_id", "org_id", "session_id"),
    )
    automation_id: Mapped[UUID]
    event_id: Mapped[UUID | None]
    caused_by: Mapped[UUID | None]
    status: Mapped[str]
    refusal: Mapped[str | None]
    hop: Mapped[int]
    session_id: Mapped[UUID | None]
    opened: Mapped[bool]
    budget_id: Mapped[UUID | None]
    reserved_micros: Mapped[int] = mapped_column(BigInteger)
    event_text: Mapped[str]
    started_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
