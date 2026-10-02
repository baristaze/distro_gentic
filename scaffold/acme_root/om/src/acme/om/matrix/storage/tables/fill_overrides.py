from typing import Any

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class FillOverrides(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's own choice of fill, one row a model role, which the unique
    index led by org_id holds, so org_id gets no index of its own."""

    __tablename__ = "fill_overrides"
    __org_id_index__ = False
    __table_args__ = (Index("uq_fill_overrides_org_id_role", "org_id", "role", unique=True),)
    role: Mapped[str]
    fill: Mapped[dict[str, Any]] = mapped_column(JSONB)
