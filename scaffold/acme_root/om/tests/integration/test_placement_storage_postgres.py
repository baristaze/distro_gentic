import pytest
from contracts.placement_storage import PlacementStorageContract

from acme.om.placement.storage import PlacementStorageInterface
from acme.om.placement.storage.impl.postgres import PlacementStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestPlacementStoragePostgres(PlacementStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> PlacementStorageInterface:
        return PlacementStoragePostgresImpl(pg_sessions)
