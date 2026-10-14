from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AgentSessionConnectors(IdentifiableMixin, CreatedMixin, Base):
    """What each session pinned of its tenant's connectors: one row a
    session, whose id is the session's, written once."""

    __tablename__ = "agent_session_connectors"
    connectors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
