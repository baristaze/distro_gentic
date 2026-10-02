from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class StationLineEntries(IdentifiableMixin, TrackableMixin, Base):
    """Every ask that stood in a line. A pool's line is read in rank order,
    and a session's places across every line, each by an index org_id
    leads over the entries still waiting."""

    __tablename__ = "station_line_entries"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "ix_station_line_entries_org_id_pool_id_rank",
            "org_id",
            "pool_id",
            "rank",
            postgresql_where=text("state = 'waiting'"),
        ),
        Index(
            "ix_station_line_entries_org_id_session_id",
            "org_id",
            "session_id",
            postgresql_where=text("state = 'waiting'"),
        ),
    )
    session_id: Mapped[UUID]
    pool_id: Mapped[UUID]
    station_id: Mapped[UUID | None]
    capabilities: Mapped[list[str]]
    project: Mapped[str]
    candidate: Mapped[str]
    procedure: Mapped[str]
    procedure_version: Mapped[str]
    principal: Mapped[dict[str, Any]]
    rank: Mapped[float]
    state: Mapped[str]
    lease_id: Mapped[UUID | None]
    settled_at: Mapped[datetime | None]
