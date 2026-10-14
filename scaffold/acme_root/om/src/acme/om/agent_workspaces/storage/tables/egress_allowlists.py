from typing import Any
from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class EgressAllowlists(IdentifiableMixin, TrackableMixin, Base):
    """Each agent project's egress allowlist: one row an agent project, which the unique
    index on (org_id, agent_project_id) holds, so org_id gets no index of its
    own."""

    __tablename__ = "egress_allowlists"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_egress_allowlists_org_id_agent_project_id",
            "org_id",
            "agent_project_id",
            unique=True,
        ),
    )
    agent_project_id: Mapped[UUID]
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB())
    open: Mapped[bool]
    reason: Mapped[str | None]
    version: Mapped[int]
