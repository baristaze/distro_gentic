from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.hosts.storage import HostsStorageInterface
from acme.om.hosts.storage.tables.host_credentials import HostCredentials
from acme.om.hosts.storage.tables.host_enrollment_tokens import HostEnrollmentTokens
from acme.om.hosts.storage.tables.host_pools import HostPools
from acme.om.hosts.storage.tables.hosts import Hosts
from acme.om.hosts.storage.tables.session_placements import SessionPlacements
from acme.om.hosts.types.credential import EnrollmentToken, HostCredential, Rotation
from acme.om.hosts.types.host import Host, HostReport
from acme.om.hosts.types.placement import SessionPlacement
from acme.om.hosts.types.pool import HostPool
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted, violated_constraint
from acme.om.storage.utils.translation import to_model, to_row, to_values

PURGED_IN_ORDER = (HostCredentials, Hosts, HostEnrollmentTokens, HostPools, SessionPlacements)
"""A deleted tenant's tables, each purged a batch at a time."""


class HostsStoragePostgresImpl(PgStorageBase, HostsStorageInterface):
    async def create_pool(
        self, org_id: UUID, pool: HostPool, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(HostPools, org_id, pool, outbox_rows)

    async def read_pool(self, org_id: UUID, pool_id: UUID) -> HostPool | None:
        stmt = select(HostPools).where(HostPools.org_id == org_id, HostPools.id == pool_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, HostPool)

    async def read_pools(self, org_id: UUID, limit: int) -> list[HostPool]:
        stmt = (
            select(HostPools).where(HostPools.org_id == org_id).order_by(HostPools.id).limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, HostPool) for row in rows]

    async def create_enrollment_token(
        self, org_id: UUID, token: EnrollmentToken, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(HostEnrollmentTokens, org_id, token, outbox_rows)

    async def read_enrollment_token_by_digest(
        self, digest: str
    ) -> tuple[UUID, EnrollmentToken] | None:
        stmt = select(HostEnrollmentTokens).where(HostEnrollmentTokens.digest == digest)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else (row.org_id, to_model(row, EnrollmentToken))

    async def revoke_enrollment_token(
        self,
        org_id: UUID,
        token_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> EnrollmentToken | None:
        stmt = (
            select(HostEnrollmentTokens)
            .where(HostEnrollmentTokens.org_id == org_id, HostEnrollmentTokens.id == token_id)
            .with_for_update()
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = at
                row.revoked_by = by
                row.updated_at = at
                row.updated_by = by
                for outbox_row in outbox_rows:
                    session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            token = to_model(row, EnrollmentToken)
            await session.commit()
            return token

    async def enroll_host(
        self,
        org_id: UUID,
        host: Host,
        credential: HostCredential,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._session_for(Hosts, org_id=org_id) as session:
            session.add(to_row(host, Hosts, org_id=org_id))
            session.add(to_row(credential, HostCredentials, org_id=org_id))
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise UniqueKeyTaken(
                    f"hosts {host.id}: {violated_constraint(error) or 'a unique key'} is taken"
                ) from error

    async def read_host(self, org_id: UUID, host_id: UUID) -> Host | None:
        stmt = select(Hosts).where(Hosts.org_id == org_id, Hosts.id == host_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Host)

    async def read_hosts(self, org_id: UUID, pool_id: UUID, limit: int) -> list[Host]:
        stmt = (
            select(Hosts)
            .where(Hosts.org_id == org_id, Hosts.pool_id == pool_id)
            .order_by(Hosts.id)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, Host) for row in rows]

    async def read_host_by_credential_digest(
        self, digest: str
    ) -> tuple[UUID, HostCredential, Host] | None:
        stmt = (
            select(HostCredentials, Hosts)
            .join(
                Hosts,
                (Hosts.id == HostCredentials.host_id) & (Hosts.org_id == HostCredentials.org_id),
            )
            .where(HostCredentials.digest == digest)
        )
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            found = (await session.execute(stmt)).one_or_none()
            if found is None:
                return None
            credential, host = found
            return (
                credential.org_id,
                to_model(credential, HostCredential),
                to_model(host, Host),
            )

    async def rotate_credential(
        self,
        org_id: UUID,
        retiring_id: UUID,
        at: datetime,
        retire_at: datetime,
        minted: HostCredential,
    ) -> Rotation:
        # The row lock makes a rotation once: of two rotations of one
        # credential at the same moment, the second reads it rotated.
        stmt = (
            select(HostCredentials)
            .where(
                HostCredentials.org_id == org_id,
                HostCredentials.id == retiring_id,
                HostCredentials.host_id == minted.host_id,
            )
            .with_for_update()
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            retiring = (await session.execute(stmt)).scalar_one_or_none()
            if retiring is None:
                await session.rollback()
                return Rotation.MISSING
            if retiring.rotated_at is not None:
                await session.rollback()
                return Rotation.REUSED
            await session.execute(
                update(HostCredentials)
                .where(
                    HostCredentials.org_id == org_id,
                    HostCredentials.host_id == minted.host_id,
                    HostCredentials.id != retiring_id,
                    HostCredentials.expires_at > at,
                )
                .values(expires_at=at)
            )
            retiring.rotated_at = at
            retiring.expires_at = min(retiring.expires_at, retire_at)
            session.add(to_row(minted, HostCredentials, org_id=org_id))
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise UniqueKeyTaken(
                    f"host_credentials {minted.id}: "
                    f"{violated_constraint(error) or 'a unique key'} is taken"
                ) from error
            return Rotation.ROTATED

    async def mark_seen(
        self, org_id: UUID, host_id: UUID, at: datetime, report: HostReport
    ) -> bool:
        stmt = (
            update(Hosts)
            .where(Hosts.org_id == org_id, Hosts.id == host_id)
            .values(
                last_seen_at=at,
                advertisement=report.advertisement.model_dump(mode="json"),
                exec_version=report.exec_version,
            )
            .returning(Hosts.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            seen = (await session.execute(stmt)).scalar_one_or_none() is not None
            await session.commit()
            return seen

    async def revoke_host(
        self,
        org_id: UUID,
        host_id: UUID,
        at: datetime,
        by: UUID,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> Host | None:
        stmt = select(Hosts).where(Hosts.org_id == org_id, Hosts.id == host_id).with_for_update()
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if row.revoked_at is None:
                row.revoked_at = at
                row.revoked_by = by
                row.updated_at = at
                row.updated_by = by
                await session.execute(
                    update(HostCredentials)
                    .where(
                        HostCredentials.org_id == org_id,
                        HostCredentials.host_id == host_id,
                        HostCredentials.expires_at > at,
                    )
                    .values(expires_at=at)
                )
                for outbox_row in outbox_rows:
                    session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            host = to_model(row, Host)
            await session.commit()
            return host

    async def read_placement(self, org_id: UUID, session_id: UUID) -> SessionPlacement | None:
        stmt = select(SessionPlacements).where(
            SessionPlacements.org_id == org_id, SessionPlacements.session_id == session_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SessionPlacement)

    async def write_placement(
        self,
        org_id: UUID,
        placement: SessionPlacement,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        stale = PreconditionFailed(
            f"the placement of session {placement.session_id} is no longer at "
            f"version {expected_version}"
        )
        if expected_version == 0:
            try:
                created = await self._insert(SessionPlacements, org_id, placement, outbox_rows)
            except UniqueKeyTaken as error:
                raise stale from error
            if not created:
                raise stale
            return
        values = {k: v for k, v in to_values(placement, SessionPlacements).items() if k != "id"}
        # The version is in the WHERE, so two writers from one read cannot
        # both land.
        stmt = (
            update(SessionPlacements)
            .where(
                SessionPlacements.org_id == org_id,
                SessionPlacements.id == placement.id,
                SessionPlacements.session_id == placement.session_id,
                SessionPlacements.version == expected_version,
            )
            .values(**values)
            .returning(SessionPlacements.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise stale
            for outbox_row in outbox_rows:
                session.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            await session.commit()

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        purged = 0
        for table in PURGED_IN_ORDER:
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                purged += deleted(await session.execute(stmt))
                await session.commit()
        return purged
