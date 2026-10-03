"""The platform agents storage contract: the validation sessions. The cases
named in `CROSS_TENANT_CASES` are the tenant fence's evidence: each one
presents another tenant's identifier and asserts that nothing is found and
nothing changes."""

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed
from acme.om.platform_agents.storage import PlatformAgentsStorageInterface
from acme.om.platform_agents.types.validation import ValidationSession, ValidationStatus

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {"create_validation", "purge_tenant", "read_validation", "write_validation"}
)
"""Every method of `PlatformAgentsStorageInterface` that takes a tenant has a
case in this module that presents another tenant's."""


def make_validation() -> ValidationSession:
    now = utcnow()
    actor = new_id()
    return ValidationSession(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        project_id=new_id(),
        check_name="report.totals",
        head="c" * 40,
        base="b" * 40,
    )


def finished(session: ValidationSession) -> ValidationSession:
    return session.model_copy(
        update={
            "status": ValidationStatus.FINISHED,
            "run_id": new_id(),
            "finished_at": utcnow(),
            "version": session.version + 1,
        }
    )


class PlatformAgentsStorageContract:
    @pytest.fixture
    def storage(self) -> PlatformAgentsStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip(self, storage: PlatformAgentsStorageInterface) -> None:
        org = new_id()
        session = make_validation()
        assert await storage.read_validation(org, session.id) is None
        assert await storage.create_validation(org, session, ())
        assert await storage.read_validation(org, session.id) == session

    async def test_create_reports_an_existing_id_and_changes_nothing(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        org = new_id()
        session = make_validation()
        assert await storage.create_validation(org, session, ())
        assert not await storage.create_validation(
            org, session.model_copy(update={"check_name": "other"}), ()
        )
        assert await storage.read_validation(org, session.id) == session

    async def test_create_validation_under_another_tenant_is_not_read_here(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        session = make_validation()
        assert await storage.create_validation(org_a, session, ())
        assert not await storage.create_validation(org_b, session, ())
        assert await storage.read_validation(org_b, session.id) is None

    async def test_read_validation_of_another_tenant_finds_nothing(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        session = make_validation()
        assert await storage.create_validation(new_id(), session, ())
        assert await storage.read_validation(new_id(), session.id) is None

    async def test_write_validation_is_a_compare_and_set(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        org = new_id()
        session = make_validation()
        assert await storage.create_validation(org, session, ())
        done = finished(session)
        await storage.write_validation(org, done, 1, ())
        assert await storage.read_validation(org, session.id) == done
        with pytest.raises(PreconditionFailed):
            await storage.write_validation(org, finished(done), 1, ())
        assert await storage.read_validation(org, session.id) == done

    async def test_write_validation_of_another_tenant_changes_nothing(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        session = make_validation()
        assert await storage.create_validation(org_a, session, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_validation(org_b, finished(session), 1, ())
        assert await storage.read_validation(org_a, session.id) == session

    async def test_purge_tenant_takes_the_tenants_sessions_and_no_other(
        self, storage: PlatformAgentsStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        stays = make_validation()
        for _ in range(3):
            assert await storage.create_validation(gone, make_validation(), ())
        assert await storage.create_validation(kept, stays, ())
        assert await storage.purge_tenant(gone, 2) == 2
        assert await storage.purge_tenant(gone, 10) == 1
        assert await storage.purge_tenant(gone, 10) == 0
        assert await storage.read_validation(kept, stays.id) == stays
