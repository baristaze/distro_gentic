from typing import Any
from uuid import UUID

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class SessionWorkspaces(IdentifiableMixin, TrackableMixin, Base):
    """Each session's workspace: one row a session, under the session's id,
    its isolation pinned and what the cache knows between loops."""

    __tablename__ = "session_workspaces"
    # The one notice `notices` replaced leaves the mapping a release before
    # it leaves the table (ADR 0038).
    __table_args__ = (Column("notice", Text()),)
    __mapper_args__ = {"exclude_properties": ["notice"]}
    project_id: Mapped[UUID | None]
    level: Mapped[str]
    limits: Mapped[dict[str, Any]]
    egress: Mapped[str]
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    egress_source: Mapped[str]
    branch: Mapped[str]
    branch_seen: Mapped[bool]
    snapshot_ref: Mapped[str | None]
    notices: Mapped[list[str]]
    version: Mapped[int]
