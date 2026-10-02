import pytest
from contracts.playbook_storage import PlaybookStorageContract

from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.storage.impl.postgres import PlaybookStoragePostgresImpl
from acme.om.storage.impl.pg_base import LoginSessions

pytestmark = pytest.mark.integration


class TestPlaybookStoragePostgres(PlaybookStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: LoginSessions) -> PlaybookStorageInterface:
        return PlaybookStoragePostgresImpl(pg_sessions)
