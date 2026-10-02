from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class HostEnrollmentTokens(IdentifiableMixin, TrackableMixin, Base):
    """The tokens a tenant issued to enroll hosts into a pool. The digest is
    unique across tenants: a host's call names no tenant, and the digest is
    how the token is found."""

    __tablename__ = "host_enrollment_tokens"
    __table_args__ = (Index("uq_host_enrollment_tokens_digest", "digest", unique=True),)
    pool_id: Mapped[UUID]
    digest: Mapped[str]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None]
