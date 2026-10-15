import pytest

from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.storage.impl.memory import EvidenceStorageMemoryImpl
from acme.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl

from contracts.evidence_storage import EvidenceStorageContract


class TestEvidenceStorageMemory(EvidenceStorageContract):
    @pytest.fixture
    def storage(self) -> EvidenceStorageInterface:
        return EvidenceStorageMemoryImpl(OutboxStorageMemoryImpl())
