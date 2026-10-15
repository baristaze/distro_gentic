from uuid import UUID

from sqlalchemy import Index
from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, CreatedMixin, IdentifiableMixin


class AgentPlaybookInvocations(IdentifiableMixin, CreatedMixin, Base):
    """The agent playbooks each session invoked: one row a version in a session,
    which the unique index on (org_id, agent_session_id, agent_playbook_id) holds and
    the read of a session's gates uses, so org_id gets no index of its own."""

    __tablename__ = "agent_playbook_invocations"
    __org_id_index__ = False
    __table_args__ = (
        Index(
            "uq_agent_playbook_invocations_org_id_session_id_agent_playbook",
            "org_id",
            "agent_session_id",
            "agent_playbook_id",
            unique=True,
        ),
    )
    agent_session_id: Mapped[UUID]
    agent_playbook_id: Mapped[UUID]
    name: Mapped[str]
    version: Mapped[int]
    invoked_by: Mapped[UUID]
    pinned: Mapped[bool]
