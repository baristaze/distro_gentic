from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from acme.om.agent_automations.rules import admitted, period_start, tally
from acme.om.agent_automations.storage import AgentAutomationStorageInterface
from acme.om.agent_automations.storage.tables.agent_automation_principals import (
    AgentAutomationPrincipals,
)
from acme.om.agent_automations.storage.tables.agent_automation_runs import AgentAutomationRuns
from acme.om.agent_automations.storage.tables.agent_automations import AgentAutomations
from acme.om.agent_automations.types.agent_automation import (
    AgentAutomation,
    AgentAutomationPrincipal,
    AgentAutomationRun,
    Limits,
    RunStatus,
)
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values

STARTED = RunStatus.STARTED.value


class AgentAutomationStoragePostgresImpl(PgStorageBase, AgentAutomationStorageInterface):
    async def create_agent_automation(
        self, org_id: UUID, agent_automation: AgentAutomation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(AgentAutomations, org_id, agent_automation, outbox_rows)

    async def read_agent_automation(
        self, org_id: UUID, agent_automation_id: UUID
    ) -> AgentAutomation | None:
        stmt = select(AgentAutomations).where(
            AgentAutomations.org_id == org_id, AgentAutomations.id == agent_automation_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentAutomation)

    async def write_agent_automation(
        self, org_id: UUID, agent_automation: AgentAutomation, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        values = {
            k: v for k, v in to_values(agent_automation, AgentAutomations).items() if k != "id"
        }
        stmt = (
            update(AgentAutomations)
            .where(AgentAutomations.org_id == org_id, AgentAutomations.id == agent_automation.id)
            .values(**values)
            .returning(AgentAutomations.id)
        )
        async with self._session_for(AgentAutomations, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                return False
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()
            return True

    async def read_agent_automations(
        self, org_id: UUID, after: UUID | None, limit: int
    ) -> list[AgentAutomation]:
        stmt = select(AgentAutomations).where(AgentAutomations.org_id == org_id)
        if after is not None:
            stmt = stmt.where(AgentAutomations.id > after)
        stmt = stmt.order_by(AgentAutomations.id).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, AgentAutomation) for row in rows]

    async def admit(
        self, org_id: UUID, run: AgentAutomationRun, limits: Limits, now: datetime
    ) -> AgentAutomationRun:
        since = period_start(limits, now)
        lock = (
            select(AgentAutomations.id)
            .where(
                AgentAutomations.org_id == org_id, AgentAutomations.id == run.agent_automation_id
            )
            .with_for_update()
        )
        async with self._session_for(AgentAutomationRuns, org_id=org_id) as db:
            # The agent automation's row is held until the commit, so no other
            # admission of it reads the runs before this one lands.
            await db.execute(lock)
            held = (
                await db.execute(
                    select(AgentAutomationRuns).where(
                        AgentAutomationRuns.org_id == org_id, AgentAutomationRuns.id == run.id
                    )
                )
            ).scalar_one_or_none()
            if held is not None and held.status != RunStatus.QUEUED.value:
                stored = to_model(held, AgentAutomationRun)
                await db.rollback()
                return stored
            counting = select(AgentAutomationRuns).where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_automation_id == run.agent_automation_id,
                AgentAutomationRuns.status == STARTED,
                AgentAutomationRuns.started_at.is_not(None),
                or_(
                    AgentAutomationRuns.started_at >= since, AgentAutomationRuns.closed_at.is_(None)
                ),
            )
            counted = [
                to_model(row, AgentAutomationRun) for row in (await db.execute(counting)).scalars()
            ]
            waiting = select(func.count()).where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_automation_id == run.agent_automation_id,
                AgentAutomationRuns.status == RunStatus.QUEUED.value,
                AgentAutomationRuns.id != run.id,
            )
            queued = (await db.execute(waiting)).scalar_one()
            landed = admitted(run, limits, tally(counted, since, queued=queued), now)
            values = to_values(landed, AgentAutomationRuns)
            write = (
                insert(AgentAutomationRuns)
                .values(**values, org_id=org_id)
                .on_conflict_do_update(
                    index_elements=[AgentAutomationRuns.id],
                    set_={k: v for k, v in values.items() if k != "id"},
                )
            )
            await db.execute(write)
            await db.commit()
            return landed

    async def create_run(self, org_id: UUID, run: AgentAutomationRun) -> AgentAutomationRun:
        await self._insert(AgentAutomationRuns, org_id, run)
        stmt = select(AgentAutomationRuns).where(
            AgentAutomationRuns.org_id == org_id, AgentAutomationRuns.id == run.id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            return to_model((await session.execute(stmt)).scalar_one(), AgentAutomationRun)

    async def write_run(self, org_id: UUID, run: AgentAutomationRun) -> None:
        values = {k: v for k, v in to_values(run, AgentAutomationRuns).items() if k != "id"}
        stmt = (
            update(AgentAutomationRuns)
            .where(AgentAutomationRuns.org_id == org_id, AgentAutomationRuns.id == run.id)
            .values(**values)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()

    async def read_run(self, org_id: UUID, run_id: UUID) -> AgentAutomationRun | None:
        stmt = select(AgentAutomationRuns).where(
            AgentAutomationRuns.org_id == org_id, AgentAutomationRuns.id == run_id
        )
        found = await self._runs(org_id, stmt)
        return found[0] if found else None

    async def write_principal(
        self, org_id: UUID, principal: AgentAutomationPrincipal
    ) -> AgentAutomationPrincipal:
        values = to_values(principal, AgentAutomationPrincipals)
        # One row a tenant: a grant over a standing one keeps its id.
        stmt = (
            insert(AgentAutomationPrincipals)
            .values(**values, org_id=org_id)
            .on_conflict_do_update(
                index_elements=[AgentAutomationPrincipals.org_id],
                set_={"role": values["role"], "granted_by": values["granted_by"]},
            )
            .returning(AgentAutomationPrincipals)
        )
        async with self._session_for(AgentAutomationPrincipals, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one()
            stored = to_model(row, AgentAutomationPrincipal)
            await session.commit()
            return stored

    async def read_principal(self, org_id: UUID) -> AgentAutomationPrincipal | None:
        stmt = select(AgentAutomationPrincipals).where(AgentAutomationPrincipals.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, AgentAutomationPrincipal)

    async def read_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        stmt = (
            select(AgentAutomationRuns)
            .where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_automation_id == agent_automation_id,
            )
            .order_by(AgentAutomationRuns.created_at.desc(), AgentAutomationRuns.id.desc())
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_open_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        stmt = (
            select(AgentAutomationRuns)
            .where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_automation_id == agent_automation_id,
                AgentAutomationRuns.status == STARTED,
                AgentAutomationRuns.closed_at.is_(None),
            )
            .order_by(AgentAutomationRuns.created_at, AgentAutomationRuns.id)
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_queued_runs(
        self, org_id: UUID, agent_automation_id: UUID, limit: int
    ) -> list[AgentAutomationRun]:
        stmt = (
            select(AgentAutomationRuns)
            .where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_automation_id == agent_automation_id,
                AgentAutomationRuns.status == RunStatus.QUEUED.value,
            )
            .order_by(AgentAutomationRuns.created_at, AgentAutomationRuns.id)
            .limit(limit)
        )
        return await self._runs(org_id, stmt)

    async def read_session_run(
        self, org_id: UUID, agent_session_id: UUID
    ) -> AgentAutomationRun | None:
        stmt = (
            select(AgentAutomationRuns)
            .where(
                AgentAutomationRuns.org_id == org_id,
                AgentAutomationRuns.agent_session_id == agent_session_id,
                AgentAutomationRuns.status == STARTED,
            )
            .order_by(AgentAutomationRuns.created_at.desc(), AgentAutomationRuns.id.desc())
            .limit(1)
        )
        found = await self._runs(org_id, stmt)
        return found[0] if found else None

    async def _runs(self, org_id: UUID, stmt: object) -> list[AgentAutomationRun]:
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()  # type: ignore[call-overload]
            return [to_model(row, AgentAutomationRun) for row in rows]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (AgentAutomationRuns, AgentAutomations, AgentAutomationPrincipals):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
