"""Storage of the automations swimlane: the tenant's automations, and the
record of every firing. Every operation takes org_id first."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from acme.om.automations.types.automation import (
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Limits,
)
from acme.om.outbox.types.row import OutboxRow


class AutomationStorageInterface(ABC):
    @abstractmethod
    async def create_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already."""
        ...

    @abstractmethod
    async def read_automation(self, org_id: UUID, automation_id: UUID) -> Automation | None: ...

    @abstractmethod
    async def write_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """A stored automation as changed, with the rows that announce it, in
        one commit. False, with nothing landed, when the tenant holds no such
        automation."""
        ...

    @abstractmethod
    async def read_automations(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Automation]:
        """The tenant's automations by id, strictly after `after`."""
        ...

    @abstractmethod
    async def admit(
        self, org_id: UUID, run: AutomationRun, limits: Limits, now: datetime
    ) -> AutomationRun:
        """A run asking to start at `now`, written as its limits leave it
        (`automations.rules.admitted`), with what its automation's runs hold
        in the period that ends now, and how many others wait in its queue,
        read in the same write, which no other admission of the automation
        shares. A run written already as queued is written over; one written
        otherwise answers as stored."""
        ...

    @abstractmethod
    async def create_run(self, org_id: UUID, run: AutomationRun) -> AutomationRun:
        """A run that asks no limit, such as a refusal; one written already
        answers as stored."""
        ...

    @abstractmethod
    async def write_run(self, org_id: UUID, run: AutomationRun) -> None:
        """A run's change after it was admitted: its session, its budget, its
        close, or a queued run refused."""
        ...

    @abstractmethod
    async def read_run(self, org_id: UUID, run_id: UUID) -> AutomationRun | None: ...

    @abstractmethod
    async def write_principal(
        self, org_id: UUID, principal: AutomationPrincipal
    ) -> AutomationPrincipal:
        """The tenant's automation principal granted: the one row of the
        tenant, its role and its granter written over when it stands, its
        id kept. Answers the row as stored."""
        ...

    @abstractmethod
    async def read_principal(self, org_id: UUID) -> AutomationPrincipal | None: ...

    @abstractmethod
    async def read_runs(self, org_id: UUID, automation_id: UUID, limit: int) -> list[AutomationRun]:
        """The automation's runs, newest first."""
        ...

    @abstractmethod
    async def read_open_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        """Its started runs not yet closed, oldest first."""
        ...

    @abstractmethod
    async def read_queued_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        """Its queued runs, oldest first."""
        ...

    @abstractmethod
    async def read_session_run(self, org_id: UUID, session_id: UUID) -> AutomationRun | None:
        """The latest started run that names the session."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each kind of a deleted tenant past its
        retention, its automation principal among them; returns how many
        went."""
        ...
