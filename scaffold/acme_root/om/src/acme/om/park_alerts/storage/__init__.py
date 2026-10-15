"""Storage of the park alerts swimlane: who was told what waits on them,
on which channel. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.park_alerts.types.park_alert import ParkAlert


class ParkAlertStorageInterface(ABC):
    @abstractmethod
    async def create_park_alert(self, org_id: UUID, park_alert: ParkAlert) -> bool:
        """The create; False, with nothing landed, when the id is written
        already."""
        ...

    @abstractmethod
    async def read_park_alert(self, org_id: UUID, park_alert_id: UUID) -> ParkAlert | None: ...

    @abstractmethod
    async def read_park_alerts(self, org_id: UUID, recipient: UUID, limit: int) -> list[ParkAlert]:
        """A recipient's park alerts, newest first."""
        ...

    @abstractmethod
    async def mark_read(
        self, org_id: UUID, recipient: UUID, park_alert_id: UUID, at: datetime
    ) -> ParkAlert | None:
        """The recipient's park alert marked read at `at`, or as marked
        before: the first mark holds. None when the recipient holds no
        park alert of that id."""
        ...

    @abstractmethod
    async def purge_agent_session(self, org_id: UUID, agent_session_id: UUID, limit: int) -> int:
        """At most `limit` of the park alerts of a session the sweep
        purges; returns how many went."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of a deleted tenant past its retention; returns
        how many went."""
        ...
