import pytest
from contracts.intake_storage import IntakeStorageContract

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.impl.memory import IntakeStorageMemoryImpl


class TestIntakeStorageMemory(IntakeStorageContract):
    @pytest.fixture
    def storage(self) -> IntakeStorageInterface:
        return IntakeStorageMemoryImpl()
