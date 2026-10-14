from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class AgentProjects(IdentifiableMixin, TrackableMixin, Base):
    """One row per agent project of a tenant, with the repository it binds and the
    workspace base its sessions' workspaces start from, if it names one."""

    __tablename__ = "agent_projects"
    name: Mapped[str]
    repository: Mapped[dict[str, Any]] = mapped_column(JSONB())
    workspace_snapshots: Mapped[bool] = mapped_column(server_default=text("true"))
    workspace_base: Mapped[dict[str, Any] | None] = mapped_column(JSONB())
