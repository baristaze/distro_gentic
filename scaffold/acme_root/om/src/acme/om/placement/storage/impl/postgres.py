from uuid import UUID

from sqlalchemy import select, update

from acme.om.base import EMPTY_UUID
from acme.om.exceptions import PreconditionFailed
from acme.om.placement.storage import PlacementStorageInterface, ShareToCarry
from acme.om.placement.storage.tables.fair_shares import FairShares
from acme.om.placement.types.share import FairShare
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_values


class PlacementStoragePostgresImpl(PgStorageBase, PlacementStorageInterface):
    async def read_share(self, org_id: UUID) -> FairShare | None:
        stmt = select(FairShares).where(FairShares.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, FairShare)

    async def create_share(self, org_id: UUID, share: FairShare) -> bool:
        return await self._insert(FairShares, org_id, share, cap_carried=True)

    async def write_share(self, org_id: UUID, share: FairShare, expected_version: int) -> None:
        values = {k: v for k, v in to_values(share, FairShares).items() if k != "id"}
        # The version is in the WHERE, so two writers from one snapshot
        # cannot both land.
        stmt = (
            update(FairShares)
            .where(
                FairShares.id == share.id,
                FairShares.org_id == org_id,
                FairShares.version == expected_version,
            )
            .values(**values, cap_carried=True)
            .returning(FairShares.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            if (await session.execute(stmt)).scalar_one_or_none() is None:
                await session.rollback()
                raise PreconditionFailed(
                    f"fair share {share.id} is no longer at version {expected_version}"
                )
            await session.commit()

    async def read_uncarried(self, limit: int) -> list[ShareToCarry]:
        stmt = (
            select(FairShares)
            .where(FairShares.cap_carried.is_(False))
            .order_by(FairShares.id)
            .limit(limit)
        )
        # Every tenant's shares, so the system scope, spelled here.
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [
            ShareToCarry(
                org_id=row.org_id, share=to_model(row, FairShare), concurrency=row.concurrency
            )
            for row in rows
        ]

    async def mark_carried(self, org_id: UUID, share_id: UUID) -> bool:
        stmt = (
            update(FairShares)
            .where(
                FairShares.id == share_id,
                FairShares.org_id == org_id,
                FairShares.cap_carried.is_(False),
            )
            .values(cap_carried=True)
            .returning(FairShares.id)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            marked = (await session.execute(stmt)).scalar_one_or_none() is not None
            await session.commit()
            return marked

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        stmt = delete_batch(FairShares, FairShares.org_id == org_id, limit=limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            purged = deleted(await session.execute(stmt))
            await session.commit()
            return purged
