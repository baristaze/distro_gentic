from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Stations(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's stations, read a pool at a time. The row is the lease
    store's anchor: a grant is a write on it conditional on `held_until`
    and `token`. org_id leads the one compound index, so it gets none of
    its own."""

    __tablename__ = "stations"
    __org_id_index__ = False
    __table_args__ = (Index("ix_stations_org_id_pool_id", "org_id", "pool_id"),)
    lab_id: Mapped[UUID]
    pool_id: Mapped[UUID]
    name: Mapped[str]
    capabilities: Mapped[list[str]]
    hold_seconds: Mapped[int]
    token: Mapped[int]
    lease_id: Mapped[UUID | None]
    held_until: Mapped[datetime | None]
