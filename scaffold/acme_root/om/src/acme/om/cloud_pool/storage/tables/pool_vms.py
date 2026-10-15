from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class PoolVms(GlobalIdentifiableMixin, CreatedMixin, Base):
    """The VMs the cloud pool started, the platform's own rows: a warm
    VM names no tenant until a session claims it. Read by the session
    it serves, by the key it was handed, and all at once by the sweep."""

    __tablename__ = "pool_vms"
    __table_args__ = (
        Index("ix_pool_vms_tenant_id_agent_session_id", "tenant_id", "agent_session_id"),
        Index("uq_pool_vms_key_digest", "key_digest", unique=True),
        Index("uq_pool_vms_name", "name", unique=True),
    )
    name: Mapped[str]
    egress_open: Mapped[bool]
    tenant_id: Mapped[UUID | None]
    agent_session_id: Mapped[UUID | None]
    pool_id: Mapped[UUID | None]
    bound_by: Mapped[UUID | None]
    host_id: Mapped[UUID | None]
    key_digest: Mapped[str | None]
    restored_from: Mapped[UUID | None]
    started_at: Mapped[datetime | None]
    bound_at: Mapped[datetime | None]
    sealed_at: Mapped[datetime | None]
