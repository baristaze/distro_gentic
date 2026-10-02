from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from acme.integrations.model_providers.types import ProviderName
from acme.om.exceptions import PreconditionFailed
from acme.om.outbox.storage.tables.outbox_rows import OutboxRows
from acme.om.outbox.types.row import OutboxRow
from acme.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted
from acme.om.storage.utils.translation import to_model, to_row, to_values
from acme.om.trust.storage import TrustStorageInterface
from acme.om.trust.storage.tables.content_grants import ContentGrants
from acme.om.trust.storage.tables.provider_keys import ProviderKeys
from acme.om.trust.storage.tables.secret_declarations import SecretDeclarations
from acme.om.trust.types.grant import ContentGrant
from acme.om.trust.types.provider_key import KeyStatus, ProviderKey
from acme.om.trust.types.secret import SecretDeclaration


class TrustStoragePostgresImpl(PgStorageBase, TrustStorageInterface):
    # Secret declarations.

    async def create_declaration(
        self, org_id: UUID, declaration: SecretDeclaration, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        return await self._insert(SecretDeclarations, org_id, declaration, outbox_rows)

    async def read_declaration(self, org_id: UUID, name: str) -> SecretDeclaration | None:
        stmt = select(SecretDeclarations).where(
            SecretDeclarations.org_id == org_id, SecretDeclarations.name == name
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, SecretDeclaration)

    async def read_declarations(
        self, org_id: UUID, after: str | None, limit: int
    ) -> list[SecretDeclaration]:
        stmt = select(SecretDeclarations).where(SecretDeclarations.org_id == org_id)
        if after is not None:
            stmt = stmt.where(SecretDeclarations.name > after)
        stmt = stmt.order_by(SecretDeclarations.name).limit(limit)
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, SecretDeclaration) for row in rows]

    # Provider keys.

    async def create_key(
        self,
        org_id: UUID,
        key: ProviderKey,
        replaced: ProviderKey | None,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        async with self._session_for(ProviderKeys, org_id=org_id) as db:
            if replaced is not None:
                # The version read is in the WHERE, so two rotations from one
                # snapshot cannot both land.
                values = {k: v for k, v in to_values(replaced, ProviderKeys).items() if k != "id"}
                moved = (
                    update(ProviderKeys)
                    .where(
                        ProviderKeys.id == replaced.id,
                        ProviderKeys.org_id == org_id,
                        ProviderKeys.version == replaced.version - 1,
                    )
                    .values(**values)
                    .returning(ProviderKeys.id)
                )
                if (await db.execute(moved)).scalar_one_or_none() is None:
                    await db.rollback()
                    raise PreconditionFailed(f"provider key {replaced.id} moved meanwhile")
            db.add(to_row(key, ProviderKeys, org_id=org_id))
            for outbox_row in outbox_rows:
                db.add(to_row(outbox_row, OutboxRows, org_id=org_id))
            try:
                await db.commit()
            except IntegrityError as error:
                # The one live key a provider, or the id: either way another
                # write landed first.
                await db.rollback()
                raise PreconditionFailed(
                    f"a live {key.provider.value} key landed meanwhile"
                ) from error

    async def read_live_key(self, org_id: UUID, provider: ProviderName) -> ProviderKey | None:
        stmt = select(ProviderKeys).where(
            ProviderKeys.org_id == org_id,
            ProviderKeys.provider == provider.value,
            ProviderKeys.status == KeyStatus.LIVE.value,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ProviderKey)

    async def read_keys(self, org_id: UUID, limit: int) -> list[ProviderKey]:
        stmt = (
            select(ProviderKeys)
            .where(ProviderKeys.org_id == org_id)
            .order_by(ProviderKeys.created_at.desc(), ProviderKeys.id.desc())
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [to_model(row, ProviderKey) for row in rows]

    async def touch_key(self, org_id: UUID, key_id: UUID, at: datetime) -> None:
        stmt = (
            update(ProviderKeys)
            .where(
                ProviderKeys.id == key_id,
                ProviderKeys.org_id == org_id,
                or_(ProviderKeys.last_used_at.is_(None), ProviderKeys.last_used_at < at),
            )
            .values(last_used_at=at)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()

    # Content grants.

    async def write_grant(self, org_id: UUID, grant: ContentGrant) -> ContentGrant:
        # One grant an identity in a tenant: the unique index decides, so two
        # grants written at once leave one, whichever landed last.
        stmt = (
            insert(ContentGrants)
            .values(**to_values(grant, ContentGrants), org_id=org_id)
            .on_conflict_do_update(
                index_elements=[ContentGrants.org_id, ContentGrants.identity_id],
                set_={
                    "id": grant.id,
                    "created_at": grant.created_at,
                    "expires_at": grant.expires_at,
                },
            )
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            await session.execute(stmt)
            await session.commit()
            return grant

    async def read_grant(self, org_id: UUID, identity_id: UUID) -> ContentGrant | None:
        stmt = select(ContentGrants).where(
            ContentGrants.org_id == org_id, ContentGrants.identity_id == identity_id
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, ContentGrant)

    async def delete_grant(self, org_id: UUID, identity_id: UUID) -> bool:
        stmt = delete_batch(
            ContentGrants,
            ContentGrants.org_id == org_id,
            ContentGrants.identity_id == identity_id,
            limit=1,
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            gone = deleted(await session.execute(stmt))
            await session.commit()
            return gone > 0

    # The sweep.

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        gone = 0
        for table in (SecretDeclarations, ProviderKeys, ContentGrants):
            stmt = delete_batch(table, table.org_id == org_id, limit=limit)
            async with self._session_for(stmt, org_id=org_id) as session:
                gone += deleted(await session.execute(stmt))
                await session.commit()
        return gone
