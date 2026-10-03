from datetime import datetime
from uuid import UUID

from acme.om.automations.rules import admitted, holds, period_start, tally
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.types.automation import (
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Limits,
    RunStatus,
)
from acme.om.outbox.storage import OutboxLandingInterface
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.memory_base import MemoryStorageBase, MemoryTable


class AutomationStorageMemoryImpl(MemoryStorageBase, AutomationStorageInterface):
    def __init__(self, outbox: OutboxLandingInterface | None = None) -> None:
        super().__init__(outbox)
        self._automations: MemoryTable[Automation] = {}
        self._runs: MemoryTable[AutomationRun] = {}
        self._principals: MemoryTable[AutomationPrincipal] = {}

    async def create_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            return self._insert(self._automations, org_id, automation, outbox_rows)

    async def read_automation(self, org_id: UUID, automation_id: UUID) -> Automation | None:
        return self._get(self._automations, org_id, automation_id)

    async def write_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        async with self._lock:
            if self._get(self._automations, org_id, automation.id) is None:
                return False
            self._put(self._automations, org_id, automation, outbox_rows)
            return True

    async def read_automations(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Automation]:
        rows = sorted(self._rows(self._automations, org_id), key=lambda a: a.id)
        return [a for a in rows if after is None or a.id > after][:limit]

    async def admit(
        self, org_id: UUID, run: AutomationRun, limits: Limits, now: datetime
    ) -> AutomationRun:
        since = period_start(limits, now)
        async with self._lock:
            held = self._get(self._runs, org_id, run.id)
            if held is not None and held.status is not RunStatus.QUEUED:
                return held
            mine = [
                r for r in self._rows(self._runs, org_id) if r.automation_id == run.automation_id
            ]
            counted = [r for r in mine if holds(r, since)]
            queued = sum(r.status is RunStatus.QUEUED and r.id != run.id for r in mine)
            landed = admitted(run, limits, tally(counted, since, queued=queued), now)
            self._put(self._runs, org_id, landed)
            return landed

    async def create_run(self, org_id: UUID, run: AutomationRun) -> AutomationRun:
        async with self._lock:
            held = self._get(self._runs, org_id, run.id)
            if held is not None:
                return held
            self._put(self._runs, org_id, run)
            return run

    async def write_run(self, org_id: UUID, run: AutomationRun) -> None:
        async with self._lock:
            if self._get(self._runs, org_id, run.id) is not None:
                self._put(self._runs, org_id, run)

    async def read_run(self, org_id: UUID, run_id: UUID) -> AutomationRun | None:
        return self._get(self._runs, org_id, run_id)

    async def write_principal(
        self, org_id: UUID, principal: AutomationPrincipal
    ) -> AutomationPrincipal:
        async with self._lock:
            held = next(iter(self._rows(self._principals, org_id)), None)
            if held is not None:
                principal = principal.model_copy(update={"id": held.id})
            self._put(self._principals, org_id, principal)
            return principal

    async def read_principal(self, org_id: UUID) -> AutomationPrincipal | None:
        return next(iter(self._rows(self._principals, org_id)), None)

    async def read_runs(self, org_id: UUID, automation_id: UUID, limit: int) -> list[AutomationRun]:
        rows = [r for r in self._rows(self._runs, org_id) if r.automation_id == automation_id]
        return sorted(rows, key=lambda r: (r.created_at, r.id), reverse=True)[:limit]

    async def read_open_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        rows = [
            r
            for r in self._rows(self._runs, org_id)
            if r.automation_id == automation_id
            and r.status is RunStatus.STARTED
            and r.closed_at is None
        ]
        return sorted(rows, key=lambda r: (r.created_at, r.id))[:limit]

    async def read_queued_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        rows = [
            r
            for r in self._rows(self._runs, org_id)
            if r.automation_id == automation_id and r.status is RunStatus.QUEUED
        ]
        return sorted(rows, key=lambda r: (r.created_at, r.id))[:limit]

    async def read_session_run(self, org_id: UUID, session_id: UUID) -> AutomationRun | None:
        rows = [
            r
            for r in self._rows(self._runs, org_id)
            if r.session_id == session_id and r.status is RunStatus.STARTED
        ]
        return max(rows, key=lambda r: (r.created_at, r.id), default=None)

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        async with self._lock:
            return (
                _drop(self._automations, org_id, limit)
                + _drop(self._runs, org_id, limit)
                + _drop(self._principals, org_id, limit)
            )


def _drop[E: Automation | AutomationRun | AutomationPrincipal](
    table: MemoryTable[E], org_id: UUID, limit: int
) -> int:
    ids = [row.id for org, row in table.values() if org == org_id][:limit]
    for row_id in ids:
        del table[row_id]
    return len(ids)
