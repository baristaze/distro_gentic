from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AccountLinks(IdentifiableMixin, CreatedMixin, Base):
    """Outside accounts mapped to users of the tenant: one row an account,
    which the unique index on (org_id, integration, external_id) holds and
    the router's read uses, so org_id gets no index of its own."""

    __tablename__ = "account_links"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_account_links_org_id_integration_external_id",
            "org_id",
            "integration",
            "external_id",
            unique=True,
        ),
    )
    integration: Mapped[str]
    external_id: Mapped[str]
    user_id: Mapped[UUID]
    created_by: Mapped[UUID]
