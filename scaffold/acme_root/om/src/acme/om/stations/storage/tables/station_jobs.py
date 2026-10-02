from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class StationJobs(IdentifiableMixin, TrackableMixin, Base):
    """Every job sent under a lease, read by id: its work item names it."""

    __tablename__ = "station_jobs"
    lease_id: Mapped[UUID]
    station_id: Mapped[UUID]
    lab_id: Mapped[UUID]
    session_id: Mapped[UUID]
    token: Mapped[int]
    project: Mapped[str]
    candidate: Mapped[str]
    procedure: Mapped[str]
    procedure_version: Mapped[str]
    commands: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    state: Mapped[str]
    claim: Mapped[dict[str, Any] | None]
    run_id: Mapped[UUID | None]
    finished_at: Mapped[datetime | None]
