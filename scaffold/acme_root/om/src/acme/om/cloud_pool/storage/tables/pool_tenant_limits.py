from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class PoolTenantLimits(IdentifiableMixin, TrackableMixin, Base):
    """One row per tenant an operator gave a maximum of its own: the VMs
    its sessions hold at once, read at each of its claims."""

    __tablename__ = "pool_tenant_limits"
    # org_id is its one unique index, so it gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (Index("uq_pool_tenant_limits_org_id", "org_id", unique=True),)
    most: Mapped[int]
    version: Mapped[int]
