from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AutomationPrincipals(IdentifiableMixin, CreatedMixin, Base):
    """The tenant's automation principal, one row a tenant: a firing reads it
    by org_id, which the unique index serves."""

    __tablename__ = "automation_principals"
    __org_id_index__ = False
    __table_args__ = (Index("uq_automation_principals_org_id", "org_id", unique=True),)
    role: Mapped[str]
    granted_by: Mapped[UUID]
