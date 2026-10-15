import pytest

from acme.om.intake.storage import IntakeStorageInterface
from acme.om.intake.storage.impl.memory import IntakeStorageMemoryImpl

from contracts.intake_storage import IntakeStorageContract


class TestIntakeStorageMemory(IntakeStorageContract):
    @pytest.fixture
    def storage(self) -> IntakeStorageInterface:
        return IntakeStorageMemoryImpl()
