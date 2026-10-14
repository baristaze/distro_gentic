from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AgentKnowledgeRecalls(IdentifiableMixin, CreatedMixin, Base):
    """The entries each session recalled, at the version it recalled: one row
    an entry in a session, which the unique index on (org_id, session_id,
    entry_id) holds and the read of a session's recalls uses, so org_id gets
    no index of its own."""

    __tablename__ = "agent_knowledge_recalls"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_agent_knowledge_recalls_org_id_session_id_entry_id",
            "org_id",
            "session_id",
            "entry_id",
            unique=True,
        ),
    )
    session_id: Mapped[UUID]
    entry_id: Mapped[UUID]
    version: Mapped[int]
