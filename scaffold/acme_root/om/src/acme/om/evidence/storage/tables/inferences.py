from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class Inferences(IdentifiableMixin, CreatedMixin, Base):
    """Every hypothesis and finding, one row each, written once with the
    runs it cites. What one says stays in the step that states it. The
    serving logins hold SELECT and INSERT here, and the purge login SELECT
    and DELETE (ADR 1002, ADR 1010)."""

    __tablename__ = "inferences"
    __org_id_index__ = False
    __table_args__ = (Index("ix_inferences_org_id_session_id_id", "org_id", "session_id", "id"),)
    session_id: Mapped[UUID]
    step_id: Mapped[UUID]
    kind: Mapped[str]
    resolves: Mapped[UUID | None]
    stance: Mapped[str | None]
    supports: Mapped[list[str]]
    refutes: Mapped[list[str]]
