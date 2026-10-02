import pytest
from contracts.matrix_storage import MatrixStorageContract, MatrixTenantStorageContract

from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.storage.impl.memory import (
    MatrixStorageMemoryImpl,
    MatrixTenantStorageMemoryImpl,
)


class TestMatrixStorageMemory(MatrixStorageContract):
    @pytest.fixture
    def storage(self) -> MatrixStorageInterface:
        return MatrixStorageMemoryImpl()


class TestMatrixTenantStorageMemory(MatrixTenantStorageContract):
    @pytest.fixture
    def storage(self) -> MatrixTenantStorageInterface:
        return MatrixTenantStorageMemoryImpl()
