from datetime import datetime
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class StationLeases(IdentifiableMixin, TrackableMixin, Base):
    """Every lease granted. The unique index over a station's leases that
    have not ended is the second fence of one live lease per station,
    behind the grant's conditional write on the station's row; org_id
    leads it, so it gets no index of its own."""

    __tablename__ = "station_leases"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_station_leases_org_id_station_id_live",
            "org_id",
            "station_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )
    station_id: Mapped[UUID]
    lab_id: Mapped[UUID]
    pool_id: Mapped[UUID]
    entry_id: Mapped[UUID]
    session_id: Mapped[UUID]
    token: Mapped[int]
    expires_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    ended: Mapped[str | None]
