"""The platform's cases of the work storage contract, over Postgres."""

import pytest

from acme.om.storage.impl.pg_base import SessionFactory
from acme.om.storage.roles import DatabaseRole
from acme.om.work.storage import WorkStorageInterface
from acme.om.work.storage.impl.postgres import WorkStoragePostgresImpl

from contracts.platform_work_storage import PlatformWorkStorageContract

pytestmark = pytest.mark.integration


class TestPlatformWorkStoragePostgres(PlatformWorkStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> WorkStorageInterface:
        return WorkStoragePostgresImpl(pg_sessions)
