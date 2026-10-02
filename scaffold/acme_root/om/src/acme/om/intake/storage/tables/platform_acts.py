from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class PlatformActs(IdentifiableMixin, CreatedMixin, Base):
    """The acts sessions made through the platform's account: one row a name
    in an integration, which the unique index on (org_id, integration, ref)
    holds and the router's read uses, so org_id gets no index of its own."""

    __tablename__ = "platform_acts"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_platform_acts_org_id_integration_ref", "org_id", "integration", "ref", unique=True
        ),
    )
    integration: Mapped[str]
    ref: Mapped[str]
    session_id: Mapped[UUID]
