from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, GlobalIdentifiableMixin, TrackableMixin


class PoolLimits(GlobalIdentifiableMixin, TrackableMixin, Base):
    """The cloud pool's own limits, the platform's rows: one per version an
    operator wrote, so every write stays with who made it. The highest
    version holds, and its unique index lets one of two writes from one
    version land."""

    __tablename__ = "pool_limits"
    __table_args__ = (Index("uq_pool_limits_version", "version", unique=True),)
    warm: Mapped[int]
    most: Mapped[int]
    tenant_most: Mapped[int]
    version: Mapped[int]
