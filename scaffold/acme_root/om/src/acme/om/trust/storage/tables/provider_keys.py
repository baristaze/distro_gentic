from datetime import datetime

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ProviderKeys(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's provider keys by reference, the row's id. A tenant's keys
    are read newest first, which the index on (org_id, created_at) serves,
    so org_id gets no index of its own. The partial unique index holds one
    live key a provider; it guards the writes, and no read plans on it. No
    column holds a value."""

    __tablename__ = "provider_keys"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_provider_keys_org_id_created_at", "org_id", "created_at"),
        Index(
            "uq_provider_keys_org_id_provider_live",
            "org_id",
            "provider",
            unique=True,
            postgresql_where=text("status = 'live'"),
        ),
    )
    provider: Mapped[str]
    status: Mapped[str]
    last_used_at: Mapped[datetime | None]
    version: Mapped[int]
