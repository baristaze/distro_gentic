from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from acme.om.base import EMPTY_UUID
from acme.om.cloud_pool.storage import CloudPoolStorageInterface
from acme.om.cloud_pool.storage.impl.postgres import CloudPoolStoragePostgresImpl
from acme.om.cloud_pool.storage.tables.pool_erasures import PoolErasures
from acme.om.cloud_pool.storage.tables.pool_vms import PoolVms
from acme.om.storage.impl.pg_base import LoginSessions

from contracts.cloud_pool_storage import CloudPoolStorageContract

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
    async with storage._session_for(PoolVms, org_id=EMPTY_UUID) as session:
        await session.execute(delete(PoolVms))
        await session.execute(delete(PoolErasures))
        await session.commit()
