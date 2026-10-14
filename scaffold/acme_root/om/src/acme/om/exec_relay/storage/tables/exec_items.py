from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Index, LargeBinary, text
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class ExecItems(IdentifiableMixin, TrackableMixin, Base):
    """Each operation a session's calls sent across a wall. A call's items
    are read together, and a session's go with it, under the compound index
    org_id leads, so it gets none of its own."""

    __tablename__ = "exec_items"
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_exec_items_org_id_session_id_key", "org_id", "session_id", "key"),
        # The sweep reads running items whose lease ended, across tenants.
        Index(
            "ix_exec_items_lease_expires_at_running",
            "lease_expires_at",
            postgresql_where=text("state = 'running'"),
        ),
    )
    session_id: Mapped[UUID]
    key: Mapped[UUID]
    operation: Mapped[str]
    effect: Mapped[str]
    host_id: Mapped[UUID]
    location: Mapped[str]
    spec: Mapped[dict[str, Any]]
    deadline: Mapped[datetime]
    epoch: Mapped[int | None]
    request: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str]
    dispatch: Mapped[int]
    row_id: Mapped[UUID]
    claim: Mapped[dict[str, Any] | None]
    lease_expires_at: Mapped[datetime | None]
    outcome: Mapped[dict[str, Any] | None]
    output: Mapped[bytes | None] = mapped_column(LargeBinary)
    result_sha256: Mapped[str | None]
    settled_at: Mapped[datetime | None]
    version: Mapped[int]
