from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class PoolErasures(GlobalIdentifiableMixin, CreatedMixin, Base):
    """The erasures the cloud pool owes, the platform's own rows: one per
    session whose disks are to go, read oldest first by the sweep."""

    __tablename__ = "pool_erasures"
    __table_args__ = (
        Index(
            "uq_pool_erasures_tenant_id_agent_session_id",
            "tenant_id",
            "agent_session_id",
            unique=True,
        ),
    )
    tenant_id: Mapped[UUID]
    agent_session_id: Mapped[UUID]
