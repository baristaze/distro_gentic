from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class ExecutionRecords(IdentifiableMixin, CreatedMixin, Base):
    """Every run, one row each, written once: the serving logins hold
    SELECT and INSERT here and nothing more, and the purge login, which
    takes a run with its session or its tenant, SELECT and DELETE (ADR
    1002, ADR 1010). A session's runs are read by id, and a validation's
    by the validation, so org_id leads both indexes and gets none of its
    own."""

    __tablename__ = "execution_records"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_execution_records_org_id_session_id_id", "org_id", "session_id", "id"),
        Index("ix_execution_records_org_id_validation_id", "org_id", "validation_id"),
    )
    session_id: Mapped[UUID]
    project: Mapped[str]
    purpose: Mapped[str]
    step_id: Mapped[UUID | None]
    validation_id: Mapped[UUID | None]
    version: Mapped[str]
    dirty: Mapped[bool]
    environment: Mapped[dict[str, Any]]
    host: Mapped[str]
    isolation: Mapped[str]
    executor: Mapped[str]
    check: Mapped[str]
    check_version: Mapped[str]
    parameters: Mapped[dict[str, Any]]
    metrics: Mapped[dict[str, Any]]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]
    outcome: Mapped[str]
    cases: Mapped[dict[str, Any]]
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    dependencies: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    abort: Mapped[str | None]
