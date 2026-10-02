from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class SessionRetentionRows(IdentifiableMixin, CreatedMixin, Base):
    """One row per session of a tenant: the retention policy it took when it
    was created, as the sweep has tightened it, its expiries, and what the
    sweep did when they came."""

    __tablename__ = "session_retention"
    # A snapshot is found by its session, and the sweep's fold reads a
    # tenant's by the policy version they folded: org_id leads both, so it
    # gets no index of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("uq_session_retention_org_id_session_id", "org_id", "session_id", unique=True),
        Index("ix_session_retention_org_id_policy_version", "org_id", "policy_version"),
        # The sweep's reads across tenants: the content and the shape still
        # to expire, by when they do.
        Index(
            "ix_session_retention_content_expires_at",
            "content_expires_at",
            postgresql_where=text("content_expires_at IS NOT NULL AND content_expired_at IS NULL"),
        ),
        Index(
            "ix_session_retention_shape_expires_at",
            "shape_expires_at",
            postgresql_where=text("shape_expires_at IS NOT NULL AND shape_expired_at IS NULL"),
        ),
    )
    session_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB())
    policy_version: Mapped[int]
    at_rest: Mapped[bool]
    content_expires_at: Mapped[datetime | None]
    shape_expires_at: Mapped[datetime | None]
    content_expired_at: Mapped[datetime | None]
    destruction: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    shape_expired_at: Mapped[datetime | None]
    version: Mapped[int]
