from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class KnowledgeEntries(IdentifiableMixin, TrackableMixin, Base):
    """A tenant's knowledge. A recall and a search read the reviewed entries
    by id, which the index on (org_id, status, id) serves, so org_id gets no
    index of its own; a read by slug takes the index on (org_id, slug)."""

    __tablename__ = "knowledge_entries"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_knowledge_entries_org_id_status_id", "org_id", "status", "id"),
        Index("ix_knowledge_entries_org_id_slug", "org_id", "slug"),
    )
    trigger: Mapped[list[str]]
    text: Mapped[str]
    status: Mapped[str]
    suggested_by: Mapped[UUID | None]
    reviewed_by: Mapped[UUID | None]
    title: Mapped[str]
    version: Mapped[int]
    project_id: Mapped[UUID | None]
    slug: Mapped[str | None]
