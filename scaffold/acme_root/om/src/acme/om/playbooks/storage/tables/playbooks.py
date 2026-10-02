from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin, NamedMixin


class Playbooks(IdentifiableMixin, NamedMixin, CreatedMixin, Base):
    """Every published version, written once: one row a version of a name,
    which the unique index on (org_id, name, version) holds and the read of
    the latest uses, so org_id gets no index of its own."""

    __tablename__ = "playbooks"
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_playbooks_org_id_name_version", "org_id", "name", "version", unique=True),
    )
    version: Mapped[int]
    description: Mapped[str]
    body: Mapped[str]
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    published_by: Mapped[UUID]
