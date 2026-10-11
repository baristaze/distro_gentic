from collections.abc import AsyncIterator

import pytest
from contracts.cloud_pool_storage import CloudPoolStorageContract
from sqlalchemy import delete

from acme.om.base import EMPTY_UUID
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.impl.postgres import CloudPoolStoragePostgresImpl
from acme.om.cloud_pool.storage.tables.pool_erasures import PoolErasures
from acme.om.cloud_pool.storage.tables.pool_machines import PoolMachines
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestCloudPoolStoragePostgres(CloudPoolStorageContract):
    """The pool's tables are the platform's, read across every test: each
    one starts and ends on empty tables."""

    @pytest.fixture
    async def storage(self, pg_sessions: LoginSessions) -> AsyncIterator[CloudPoolStorageInterface]:
        storage = CloudPoolStoragePostgresImpl(pg_sessions)
        await _empty(storage)
        yield storage
        await _empty(storage)


async def _empty(storage: CloudPoolStoragePostgresImpl) -> None:
    async with storage._session_for(PoolMachines, org_id=EMPTY_UUID) as session:
        await session.execute(delete(PoolMachines))
        await session.execute(delete(PoolErasures))
        await session.commit()
