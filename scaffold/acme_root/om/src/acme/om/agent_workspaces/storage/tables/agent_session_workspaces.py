from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class AgentSessionWorkspaces(IdentifiableMixin, TrackableMixin, Base):
    """Each session's workspace: one row a session, under the session's id,
    its isolation pinned and what the cache knows between loops."""

    __tablename__ = "agent_session_workspaces"
    project_id: Mapped[UUID | None]
    level: Mapped[str]
    limits: Mapped[dict[str, Any]]
    egress: Mapped[str]
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    egress_source: Mapped[str]
    durability: Mapped[str] = mapped_column(server_default=text("'cache'"))
    base: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
    branch: Mapped[str]
    branch_seen: Mapped[bool]
    snapshot_ref: Mapped[str | None]
    notices: Mapped[list[str]]
    push_digest: Mapped[str | None]
    push_expires_at: Mapped[datetime | None]
    version: Mapped[int]
