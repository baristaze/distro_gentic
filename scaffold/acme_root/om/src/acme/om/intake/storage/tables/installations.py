from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class Installations(IdentifiableMixin, CreatedMixin, Base):
    """A system's installations of the platform, each connected by one
    tenant: the unique index on (integration, installation) spans every
    tenant, so an installation names one tenant, and the ingress's read by
    installation uses it. A tenant's own rows are read and purged by org_id."""

    __tablename__ = "installations"
    __table_args__ = (
        Index(
            "uq_installations_integration_installation",
            "integration",
            "installation",
            unique=True,
        ),
    )
    integration: Mapped[str]
    installation: Mapped[str]
    created_by: Mapped[UUID]
