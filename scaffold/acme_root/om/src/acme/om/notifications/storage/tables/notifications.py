from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class Notifications(IdentifiableMixin, CreatedMixin, Base):
    """Who was told what waits on them. A person's list is read by recipient
    and time, which the index serves; it leads with org_id, so org_id gets
    no index of its own."""

    __tablename__ = "notifications"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_notifications_org_id_recipient_created_at", "org_id", "recipient", "created_at"),
    )
    recipient: Mapped[UUID]
    session_id: Mapped[UUID]
    park_step: Mapped[UUID]
    reason: Mapped[str]
    unlock: Mapped[str]
    action: Mapped[str]
    link: Mapped[str]
    channel: Mapped[str]
    address: Mapped[str]
    provenance: Mapped[str | None]
    text: Mapped[str]
    read_at: Mapped[datetime | None]
