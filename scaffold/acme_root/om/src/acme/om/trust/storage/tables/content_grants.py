from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class ContentGrants(IdentifiableMixin, CreatedMixin, Base):
    """The operators who may open a tenant's session content: one row an
    identity in a tenant, which the unique index on (org_id, identity_id)
    holds and the reads use, so org_id gets no index of its own."""

    __tablename__ = "content_grants"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_content_grants_org_id_identity_id", "org_id", "identity_id", unique=True),
    )
    identity_id: Mapped[UUID]
    expires_at: Mapped[datetime]
