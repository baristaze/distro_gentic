from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class Validations(IdentifiableMixin, CreatedMixin, Base):
    """Every pass of the executor's, one row each, written once with the
    runs it lists, in one commit. The serving logins hold SELECT and INSERT
    here, and the purge login SELECT and DELETE (ADR 1002, ADR 1010). A
    session's are read by id, at a version or not."""

    __tablename__ = "validations"
    __org_id_index__ = False
    __table_args__ = (Index("ix_validations_org_id_session_id_id", "org_id", "session_id", "id"),)
    session_id: Mapped[UUID]
    project: Mapped[str]
    purpose: Mapped[str]
    version: Mapped[str]
    source: Mapped[str]
    executor: Mapped[str]
    results_sha256: Mapped[str]
    records: Mapped[list[str]]
