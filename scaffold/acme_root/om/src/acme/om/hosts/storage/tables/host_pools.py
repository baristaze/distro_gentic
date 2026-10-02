from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class HostPools(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's host pools, read by id or all of a tenant's at once."""

    __tablename__ = "host_pools"
    name: Mapped[str]
    region: Mapped[str]
    labels: Mapped[list[str]]
