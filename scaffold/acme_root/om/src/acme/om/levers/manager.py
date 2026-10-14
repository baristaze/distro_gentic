"""The levers swimlane: the texts a tenant customizes its agents with, a
agent_playbook or a reviewed agent knowledge entry, read before a person publishes
them by checks of their own, and read back from the sessions that stalled
after them. A check advises and never refuses a publish; its findings are
kept with the version they read, by the swimlane that keeps the lever.
What is left here is the reading, an operator's: which levers came before
a tenant's sessions stalled."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.context import OperatorContext
from acme.om.levers.types.lever import LeverReading


class LeversManagerInterface(ABC):
    @abstractmethod
    async def read_levers(
        self, admin: OperatorContext, org_id: UUID, since: datetime, until: datetime
    ) -> LeverReading:
        """The levers of the named tenant's sessions created in `[since,
        until)`, best first: for each, how often the sessions that reached
        it stalled against those that did not, and the sessions behind the
        figure. A session's stall is read from its steps' headers, never
        from what a step says, and a lever is answered by its kind, id, and
        version, never by its name or its slug. Requires `OperatorPermission.READ`, and is
        logged with the tenant and the operator. A window that does not
        end after it starts is `ValidationFailed`."""
        ...
