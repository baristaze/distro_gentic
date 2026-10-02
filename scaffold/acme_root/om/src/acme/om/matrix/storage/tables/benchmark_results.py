from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class BenchmarkResults(GlobalIdentifiableMixin, CreatedMixin, Base):
    """Every benchmark result a person recorded, one row each, written once:
    the serving logins hold no UPDATE or DELETE on it. A model's results are
    read newest first, which the index serves."""

    __tablename__ = "benchmark_results"
    __table_args__ = (
        Index("ix_benchmark_results_provider_model_created_at", "provider", "model", "created_at"),
    )
    provider: Mapped[str]
    model: Mapped[str]
    role: Mapped[str]
    benchmark: Mapped[str]
    passed: Mapped[bool]
    run: Mapped[str]
    recorded_by: Mapped[UUID]
