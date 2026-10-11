from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, IdentifiableMixin, TrackableMixin


class Projects(IdentifiableMixin, TrackableMixin, Base):
    """One row per project of a tenant, with the repository it binds."""

    __tablename__ = "projects"
    name: Mapped[str]
    repository: Mapped[dict[str, Any]] = mapped_column(JSONB())
    workspace_snapshots: Mapped[bool] = mapped_column(server_default=text("true"))
