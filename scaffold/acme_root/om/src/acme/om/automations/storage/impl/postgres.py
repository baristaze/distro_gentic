from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from acme.om.automations.rules import admitted, period_start, tally
from acme.om.automations.storage import AutomationStorageInterface
from acme.om.automations.storage.tables.automation_principals import AutomationPrincipals
from acme.om.automations.storage.tables.automation_runs import AutomationRuns
from acme.om.automations.storage.tables.automations import Automations
from acme.om.automations.types.automation import (
    Automation,
    AutomationPrincipal,
    AutomationRun,
    Limits,
    RunStatus,
)
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values

STARTED = RunStatus.STARTED.value


class AutomationStoragePostgresImpl(PgStorageBase, AutomationStorageInterface):
    async def create_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(Automations, org_id, automation, outbox_rows)

    async def read_automation(self, org_id: UUID, automation_id: UUID) -> Automation | None:
        stmt = select(Automations).where(
            Automations.org_id == org_id, Automations.id == automation_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Automation)

    async def write_automation(
        self, org_id: UUID, automation: Automation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        values = {k: v for k, v in to_values(automation, Automations).items() if k != "id"}
        stmt = (
            update(Automations)
            .where(Automations.org_id == org_id, Automations.id == automation.id)
            .values(**values)
            .returning(Automations.id)
        )
        async with self._session_for(Automations, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def read_automations(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[Automation]:
        stmt = select(Automations).where(Automations.org_id == org_id)
        if after is not None:
            stmt = stmt.where(Automations.id > after)
        stmt = stmt.order_by(Automations.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Automation) for row in rows]

    async def admit(
        self, org_id: UUID, run: AutomationRun, limits: Limits, now: datetime
    ) -> AutomationRun:
        since = period_start(limits, now)
        lock = (
            select(Automations.id)
            .where(Automations.org_id == org_id, Automations.id == run.automation_id)
            .with_for_update()
        )
        async with self._session_for(AutomationRuns, org_id=org_id) as db:
            # The automation's row is held until the commit, so no other
            # admission of it reads the runs before this one lands.
            await db.execute(lock)
            held = (
                await db.execute(
                    select(AutomationRuns).where(
                        AutomationRuns.org_id == org_id, AutomationRuns.id == run.id
                    )
                )
            ).scalar_one_or_none()
            if held is not None and held.status != RunStatus.QUEUED.value:
                stored = to_model(held, AutomationRun)
                await db.rollback()
                return stored
            counting = select(AutomationRuns).where(
                AutomationRuns.org_id == org_id,
                AutomationRuns.automation_id == run.automation_id,
                AutomationRuns.status == STARTED,
                AutomationRuns.started_at.is_not(None),
                or_(AutomationRuns.started_at >= since, AutomationRuns.closed_at.is_(None)),
            )
            counted = [
                to_model(row, AutomationRun) for row in (await db.execute(counting)).scalars()
            ]
            waiting = select(func.count()).where(
                AutomationRuns.org_id == org_id,
                AutomationRuns.automation_id == run.automation_id,
                AutomationRuns.status == RunStatus.QUEUED.value,
                AutomationRuns.id != run.id,
            )
            queued = (await db.execute(waiting)).scalar_one()
            landed = admitted(run, limits, tally(counted, since, queued=queued), now)
            values = to_values(landed, AutomationRuns)
            write = (
                insert(AutomationRuns)
                .values(**values, org_id=org_id)
                .on_conflict_do_update(
                    index_elements=[AutomationRuns.id],
                    set_={k: v for k, v in values.items() if k != "id"},
                )
            )
            await db.execute(write)
            await db.commit()
            return landed

    async def create_run(self, org_id: UUID, run: AutomationRun) -> AutomationRun:
        await self._insert(AutomationRuns, org_id, run)
        stmt = select(AutomationRuns).where(
            AutomationRuns.org_id == org_id, AutomationRuns.id == run.id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return to_model((await session.execute(stmt)).scalar_one(), AutomationRun)

    async def write_run(self, org_id: UUID, run: AutomationRun) -> None:
        values = {k: v for k, v in to_values(run, AutomationRuns).items() if k != "id"}
        stmt = (
            update(AutomationRuns)
            .where(AutomationRuns.org_id == org_id, AutomationRuns.id == run.id)
            .values(**values)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_run(self, org_id: UUID, run_id: UUID) -> AutomationRun | None:
        stmt = select(AutomationRuns).where(
            AutomationRuns.org_id == org_id, AutomationRuns.id == run_id
        )
        found = await self._runs(org_id, stmt)
        return found[0] if found else None

    async def write_principal(
        self, org_id: UUID, principal: AutomationPrincipal
    ) -> AutomationPrincipal:
        values = to_values(principal, AutomationPrincipals)
        # One row a tenant: a grant over a standing one keeps its id.
        stmt = (
            insert(AutomationPrincipals)
            .values(**values, org_id=org_id)
            .on_conflict_do_update(
                index_elements=[AutomationPrincipals.org_id],
                set_={"role": values["role"], "granted_by": values["granted_by"]},
            )
            .returning(AutomationPrincipals)
        )
        async with self._session_for(AutomationPrincipals, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one()
            stored = to_model(row, AutomationPrincipal)
            await session.commit()
            return stored

    async def read_principal(self, org_id: UUID) -> AutomationPrincipal | None:
        stmt = select(AutomationPrincipals).where(AutomationPrincipals.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AutomationPrincipal)

    async def read_runs(self, org_id: UUID, automation_id: UUID, limit: int) -> list[AutomationRun]:
        stmt = (
            select(AutomationRuns)
            .where(AutomationRuns.org_id == org_id, AutomationRuns.automation_id == automation_id)
            .order_by(AutomationRuns.created_at.desc(), AutomationRuns.id.desc())
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_open_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        stmt = (
            select(AutomationRuns)
            .where(
                AutomationRuns.org_id == org_id,
                AutomationRuns.automation_id == automation_id,
                AutomationRuns.status == STARTED,
                AutomationRuns.closed_at.is_(None),
            )
            .order_by(AutomationRuns.created_at, AutomationRuns.id)
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_queued_runs(
        self, org_id: UUID, automation_id: UUID, limit: int
    ) -> list[AutomationRun]:
        stmt = (
            select(AutomationRuns)
            .where(
                AutomationRuns.org_id == org_id,
                AutomationRuns.automation_id == automation_id,
                AutomationRuns.status == RunStatus.QUEUED.value,
            )
            .order_by(AutomationRuns.created_at, AutomationRuns.id)
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_session_run(self, org_id: UUID, session_id: UUID) -> AutomationRun | None:
        stmt = (
            select(AutomationRuns)
            .where(
                AutomationRuns.org_id == org_id,
                AutomationRuns.session_id == session_id,
                AutomationRuns.status == STARTED,
            )
            .order_by(AutomationRuns.created_at.desc(), AutomationRuns.id.desc())
            .limit(1)
        )
        found = await self._runs(org_id, stmt)
        return found[0] if found else None

    async def _runs(self, org_id: UUID, stmt: object) -> list[AutomationRun]:
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()  # type: ignore[call-overload]
            return [to_model(row, AutomationRun) for row in rows]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (AutomationRuns, Automations, AutomationPrincipals):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
