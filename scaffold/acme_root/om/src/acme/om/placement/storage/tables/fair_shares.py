from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class FairShares(IdentifiableMixin, TrackableMixin, Base):
    """Each tenant's fair share of the loops: one row a tenant, which the
    unique index on org_id holds, so it gets no index of its own."""

    __tablename__ = "fair_shares"
    __org_id_index__ = False
    __table_args__ = (Index("uq_fair_shares_org_id", "org_id", unique=True),)
    plan_tier: Mapped[str]
    own_lane: Mapped[bool]
    concurrency: Mapped[int]
    version: Mapped[int]
