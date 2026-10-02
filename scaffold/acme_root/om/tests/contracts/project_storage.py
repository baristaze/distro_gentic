"""The project storage contract: a project, written once; a session's
project row, written once and never moved, its first write standing; and
the purges. The cases named in `CROSS_TENANT_CASES` are the tenant fence's
evidence: each one presents another tenant's identifier and asserts that
nothing is found and nothing changes."""

from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.exceptions import TenantMismatch
from acme.om.projects.storage import ProjectStorageInterface
from acme.om.projects.types.binding import SessionProject
from acme.om.projects.types.project import Project, Repository

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "bind_session",
        "create_project",
        "purge_session",
        "purge_tenant",
        "read_binding",
        "read_project",
    }
)
"""Every method of `ProjectStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_project(path: str = "acme/arm") -> Project:
    now, by = utcnow(), new_id()
    return Project(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        name="the arm's firmware",
        repository=Repository(host="github.com", path=path),
    )


def make_binding(session_id: UUID, project_id: UUID) -> SessionProject:
    return SessionProject(id=session_id, created_at=utcnow(), project_id=project_id)


class ProjectStorageContract:
    @pytest.fixture
    def storage(self) -> ProjectStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_project_is_written_once(self, storage: ProjectStorageInterface) -> None:
        org = new_id()
        project = make_project()
        assert await storage.create_project(org, project, ())
        renamed = project.model_copy(update={"name": "renamed"})
        assert not await storage.create_project(org, renamed, ())
        assert await storage.read_project(org, project.id) == project
        assert await storage.read_project(org, new_id()) is None

    async def test_a_sessions_project_is_written_once_and_never_moves(
        self, storage: ProjectStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        first, second = make_project(), make_project("acme/gripper")
        for project in (first, second):
            await storage.create_project(org, project, ())
        bound = make_binding(session, first.id)
        assert await storage.bind_session(org, bound) == bound
        assert await storage.bind_session(org, make_binding(session, second.id)) == bound
        assert await storage.read_binding(org, session) == bound
        assert await storage.read_binding(org, new_id()) is None

    async def test_another_tenant_naming_a_project_or_a_session_reaches_none_of_it(
        self, storage: ProjectStorageInterface
    ) -> None:
        """A project and a session's row are their tenant's: another tenant
        that names them reads nothing, writes nothing over them, and purges
        none of them. A row that presents the holder's id is refused."""
        org_a, org_b, session = new_id(), new_id(), new_id()
        project = make_project()
        await storage.create_project(org_a, project, ())
        bound = make_binding(session, project.id)
        await storage.bind_session(org_a, bound)
        assert await storage.read_project(org_b, project.id) is None
        assert not await storage.create_project(
            org_b, project.model_copy(update={"name": "taken"}), ()
        )
        assert await storage.read_binding(org_b, session) is None
        with pytest.raises(TenantMismatch):
            await storage.bind_session(org_b, make_binding(session, new_id()))
        assert not await storage.purge_session(org_b, session)
        assert await storage.purge_tenant(org_b, 10) == 0
        assert await storage.read_project(org_a, project.id) == project
        assert await storage.read_binding(org_a, session) == bound

    async def test_a_sessions_purge_takes_its_row_alone(
        self, storage: ProjectStorageInterface
    ) -> None:
        org, session, other = new_id(), new_id(), new_id()
        project = make_project()
        await storage.create_project(org, project, ())
        for each in (session, other):
            await storage.bind_session(org, make_binding(each, project.id))
        assert await storage.purge_session(org, session)
        assert not await storage.purge_session(org, session)
        assert await storage.read_binding(org, session) is None
        assert await storage.read_binding(org, other) is not None
        assert await storage.read_project(org, project.id) == project

    async def test_a_tenants_purge_takes_its_rows_alone_sessions_first(
        self, storage: ProjectStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        kept = make_project()
        await storage.create_project(other, kept, ())
        await storage.bind_session(other, make_binding(new_id(), kept.id))
        project = make_project()
        await storage.create_project(org, project, ())
        sessions = [new_id(), new_id()]
        for session in sessions:
            await storage.bind_session(org, make_binding(session, project.id))
        assert await storage.purge_tenant(org, 2) == 2
        assert all([await storage.read_binding(org, s) is None for s in sessions])
        assert await storage.read_project(org, project.id) == project
        assert await storage.purge_tenant(org, 2) == 1
        assert await storage.read_project(org, project.id) is None
        assert await storage.purge_tenant(org, 2) == 0
        assert await storage.read_project(other, kept.id) == kept
