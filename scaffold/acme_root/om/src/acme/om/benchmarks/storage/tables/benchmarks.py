from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class Benchmarks(GlobalIdentifiableMixin, CreatedMixin, Base):
    """Every benchmark the operators recorded, one row each, no tenant's,
    written once: the serving logins hold no UPDATE or DELETE on it. A
    scenario's are read newest first, which the index serves."""

    __tablename__ = "benchmarks"
    __table_args__ = (Index("ix_benchmarks_scenario_created_at", "scenario", "created_at"),)
    scenario: Mapped[str]
    candidate: Mapped[dict[str, Any]] = mapped_column(JSONB)
    baseline: Mapped[dict[str, Any]] = mapped_column(JSONB)
    trials: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    candidate_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    baseline_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    regressed: Mapped[bool]
    recorded_by: Mapped[UUID]
