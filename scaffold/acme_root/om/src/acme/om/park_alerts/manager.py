"""The park alerts swimlane: a park that needs a person tells whoever can
clear it (the requester, the eligible approvers, a budget's owners) on
their channels, with a link to the one action that clears it where the
API serves one. Each person
is told once a park on each channel: the platform's own list, and every
account of theirs an integration holds."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agents.types.run import LoopRun
from acme.om.context import TenantContext
from acme.om.park_alerts.types.park_alert import ParkAlert


class ParkAlertsManagerInterface(ABC):
    @abstractmethod
    async def notify_park(self, ctx: TenantContext, run: LoopRun) -> tuple[ParkAlert, ...]:
        """A run that parked on what only a person clears tells exactly the
        people who may clear it, each on every channel of theirs, with the
        link to the one action where a route serves it, and answers what it
        told. A run that did not
        park, or parked on what clears by itself, tells nobody. Told once a
        park: asked again, it answers what it told, and a park that tries
        again by itself is one park across its tries."""
        ...

    @abstractmethod
    async def get_park_alerts(self, ctx: TenantContext, limit: int) -> tuple[ParkAlert, ...]:
        """The caller's own park alerts, newest first; `limit` is clamped."""
        ...

    @abstractmethod
    async def mark_read(self, ctx: TenantContext, park_alert_id: UUID) -> ParkAlert:
        """The caller's own park alert marked read; the first mark holds.
        One told to anyone else, or to another tenant, is `NotFound`."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its
        park alerts, a batch at most a call. Any other tenant returns 0."""
        ...
