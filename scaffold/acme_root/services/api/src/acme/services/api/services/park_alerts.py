"""The park alerts service: the caller's own list of what waits on them,
and a mark that one is read."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.services.api.types.park_alerts import ParkAlertView


class ParkAlertsServiceInterface(ABC):
    @abstractmethod
    async def get_park_alerts(self, ctx: TenantContext, limit: int) -> list[ParkAlertView]: ...

    @abstractmethod
    async def mark_read(self, ctx: TenantContext, park_alert_id: UUID) -> ParkAlertView: ...
