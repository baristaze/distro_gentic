from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class HostCredentials(IdentifiableMixin, CreatedMixin, Base):
    """Each credential a host was minted. The digest is unique across
    tenants, since a host's call names no tenant; a host's credentials are
    ended together when it is revoked, under the compound index org_id
    leads."""

    __tablename__ = "host_credentials"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_host_credentials_digest", "digest", unique=True),
        Index("ix_host_credentials_org_id_host_id", "org_id", "host_id"),
    )
    host_id: Mapped[UUID]
    digest: Mapped[str]
    expires_at: Mapped[datetime]
