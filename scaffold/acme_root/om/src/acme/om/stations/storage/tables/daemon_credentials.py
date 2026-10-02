from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class DaemonCredentials(IdentifiableMixin, CreatedMixin, Base):
    """Each credential a lab's daemon was minted. The digest is unique
    across tenants, since a daemon's call names no tenant; a lab's are
    ended together, under the compound index org_id leads."""

    __tablename__ = "daemon_credentials"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_daemon_credentials_digest", "digest", unique=True),
        Index("ix_daemon_credentials_org_id_lab_id", "org_id", "lab_id"),
    )
    lab_id: Mapped[UUID]
    issued_by: Mapped[UUID]
    digest: Mapped[str]
    expires_at: Mapped[datetime]
    rotated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
