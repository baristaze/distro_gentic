from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class PoolArchives(GlobalIdentifiableMixin, CreatedMixin, Base):
    """The sessions whose workspace files the cloud pool archived, the
    platform's own rows: one per session, with the latest moment it was
    known active, read oldest first by the sweep."""

    __tablename__ = "pool_archives"
    __table_args__ = (
        Index(
            "uq_pool_archives_tenant_id_agent_session_id",
            "tenant_id",
            "agent_session_id",
            unique=True,
        ),
        Index("ix_pool_archives_kept_at", "kept_at"),
    )
    tenant_id: Mapped[UUID]
    agent_session_id: Mapped[UUID]
    kept_at: Mapped[datetime]
