from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class FairShares(IdentifiableMixin, TrackableMixin, Base):
    """Each tenant's fair share of the loops: one row a tenant, which the
    unique index on org_id holds, so it gets no index of its own."""

    __tablename__ = "fair_shares"
    __org_id_index__ = False
    __table_args__ = (Index("uq_fair_shares_org_id", "org_id", unique=True),)
    plan_tier: Mapped[str]
    own_lane: Mapped[bool]
    # How many of the tenant's loops ran at once, as the release before reads
    # it. The work queue's cap holds that number, so nothing here writes it:
    # a row takes the column's default, and the sweep carries a number the
    # release before wrote into the tenant's own cap once (`cap_carried`).
    concurrency: Mapped[int] = mapped_column(server_default=text("8"))
    cap_carried: Mapped[bool] = mapped_column(server_default=text("false"))
    version: Mapped[int]
