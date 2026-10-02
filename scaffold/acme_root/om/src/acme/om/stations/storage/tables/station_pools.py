from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class StationPools(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's station pools, read by id."""

    __tablename__ = "station_pools"
    name: Mapped[str]
    job_seconds: Mapped[int]
