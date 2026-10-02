import pytest
from contracts.matrix_storage import MatrixStorageContract, MatrixTenantStorageContract

from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.storage.impl.postgres import (
    MatrixStoragePostgresImpl,
    MatrixTenantStoragePostgresImpl,
)
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestMatrixStoragePostgres(MatrixStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> MatrixStorageInterface:
        return MatrixStoragePostgresImpl(pg_sessions)


class TestMatrixTenantStoragePostgres(MatrixTenantStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> MatrixTenantStorageInterface:
        return MatrixTenantStoragePostgresImpl(pg_sessions)
