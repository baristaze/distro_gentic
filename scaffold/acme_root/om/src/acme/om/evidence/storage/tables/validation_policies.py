from typing import Any

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ValidationPolicies(IdentifiableMixin, TrackableMixin, Base):
    """Each agent project's validation policy: one row an agent project of a tenant,
    which the unique index on the two holds, so org_id gets no index of its
    own."""

    __tablename__ = "validation_policies"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_validation_policies_org_id_agent_project", "org_id", "agent_project", unique=True
        ),
    )
    agent_project: Mapped[str]
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    protected: Mapped[list[str]] = mapped_column(JSONB())
    version: Mapped[int]
