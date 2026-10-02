from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class MatrixVersions(GlobalIdentifiableMixin, CreatedMixin, Base):
    """Every version of the platform's model matrix, one row each, no
    tenant's. Its roles and rows are written once; publishing it sets its
    status and who published it, and nothing else. A version is read by its
    number, the latest first, which the unique index serves."""

    __tablename__ = "matrix_versions"
    __table_args__ = (Index("uq_matrix_versions_number", "number", unique=True),)
    number: Mapped[int]
    roles: Mapped[list[str]]
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str]
    created_by: Mapped[UUID]
    published_at: Mapped[datetime | None]
    published_by: Mapped[UUID | None]
