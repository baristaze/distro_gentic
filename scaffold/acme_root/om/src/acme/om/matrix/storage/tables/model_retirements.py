from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, GlobalIdentifiableMixin


class ModelRetirements(GlobalIdentifiableMixin, CreatedMixin, Base):
    """The models their providers retired, one row a model, which the unique
    index holds."""

    __tablename__ = "model_retirements"
    __table_args__ = (
        Index("uq_model_retirements_provider_model", "provider", "model", unique=True),
    )
    provider: Mapped[str]
    model: Mapped[str]
    recorded_by: Mapped[UUID]
