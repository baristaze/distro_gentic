from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, NamedMixin, TrackableMixin


class Connectors(IdentifiableMixin, NamedMixin, TrackableMixin, Base):
    """A tenant's connectors: one row a name, which the unique index on
    (org_id, name) holds, so org_id gets no index of its own. The reviewed
    tools and the attachments are the row's own lists, read whole."""

    __tablename__ = "connectors"
    __org_id_index__ = False
    __table_args__ = (Index("uq_connectors_org_id_name", "org_id", "name", unique=True),)
    summary: Mapped[str]
    place: Mapped[str]
    url: Mapped[str | None]
    credential_header: Mapped[str]
    credential_scheme: Mapped[str]
    secret: Mapped[str | None]
    host_server: Mapped[str | None]
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    review: Mapped[int]
    reviewed_by: Mapped[UUID | None]
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    version: Mapped[int]
