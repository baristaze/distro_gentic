from typing import Any

from sqlalchemy.orm import Mapped

from acme.om.storage.tables.base import Base, IdentifiableMixin, NamedMixin, TrackableMixin


class AgentAutomations(IdentifiableMixin, NamedMixin, TrackableMixin, Base):
    """A tenant's agent automations. A firing reads them by tenant, which the
    index on org_id serves; an admission locks its agent automation's row."""

    __tablename__ = "agent_automations"
    trigger: Mapped[dict[str, Any]]
    action: Mapped[dict[str, Any]]
    limits: Mapped[dict[str, Any]]
    runs_as: Mapped[str]
    own_events: Mapped[bool]
    enabled: Mapped[bool]
