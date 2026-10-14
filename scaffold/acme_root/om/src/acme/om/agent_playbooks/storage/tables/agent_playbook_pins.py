from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class AgentPlaybookPins(IdentifiableMixin, TrackableMixin, Base):
    """The versions pinned to kinds as their kind manuals: one row a kind in a
    project, or in none for the tenant's, which the unique index on
    (org_id, kind, project_id), its nulls not distinct, holds and the read
    of a session's kind manual uses, so org_id gets no index of its own."""

    __tablename__ = "agent_playbook_pins"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_agent_playbook_pins_org_id_kind_project_id",
            "org_id",
            "kind",
            "project_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )
    kind: Mapped[str]
    project_id: Mapped[UUID | None]
    agent_playbook_id: Mapped[UUID]
    name: Mapped[str]
    version: Mapped[int]
