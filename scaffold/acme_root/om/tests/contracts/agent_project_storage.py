"""The agent project storage contract: an agent project, created once, renamed in
place, and deleted only while no session's row names it; a session's
agent project row, written once and never moved, its first write standing; and
the purges. The cases named in `CROSS_TENANT_CASES` are the tenant fence's
evidence: each one presents another tenant's identifier and asserts that
nothing is found and nothing changes."""

from uuid import UUID

import pytest

from acme.om.agent_projects.storage import AgentProjectStorageInterface
from acme.om.agent_projects.types.agent_project import AgentProject, Repository
from acme.om.agent_projects.types.binding import SessionAgentProject
from acme.om.base import new_id, utcnow
from acme.om.exceptions import TenantMismatch

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "bind_session",
        "create_agent_project",
        "delete_agent_project",
        "purge_session",
        "purge_tenant",
        "read_binding",
        "read_agent_project",
        "read_agent_projects",
        "write_agent_project",
    }
)
"""Every method of `AgentProjectStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""


def make_agent_project(path: str = "octo/reports") -> AgentProject:
    now, by = utcnow(), new_id()
    return AgentProject(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        name="the weekly reports",
        repository=Repository(host="github.com", path=path),
    )


def make_binding(session_id: UUID, agent_project_id: UUID) -> SessionAgentProject:
    return SessionAgentProject(
        id=session_id, created_at=utcnow(), agent_project_id=agent_project_id
    )


async def in_agent_project(
    storage: AgentProjectStorageInterface, org_id: UUID, *sessions: UUID, path: str = "octo/reports"
) -> UUID:
    """A new agent project of the tenant, with each session bound to it in its
    rows, as the agent projects' start binds one: a suite's way to place a
    session it started otherwise. Answers the agent project's id."""
    agent_project = make_agent_project(path)
    assert await storage.create_agent_project(org_id, agent_project, ())
    for session_id in sessions:
        await storage.bind_session(org_id, make_binding(session_id, agent_project.id))
    return agent_project.id


class AgentProjectStorageContract:
    @pytest.fixture
    def storage(self) -> AgentProjectStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_an_agent_project_is_written_once(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org = new_id()
        agent_project = make_agent_project()
        assert await storage.create_agent_project(org, agent_project, ())
        renamed = agent_project.model_copy(update={"name": "renamed"})
        assert not await storage.create_agent_project(org, renamed, ())
        assert await storage.read_agent_project(org, agent_project.id) == agent_project
        assert await storage.read_agent_project(org, new_id()) is None

    async def test_an_agent_project_is_renamed_in_place_and_listed_by_id(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org = new_id()
        first, second = make_agent_project(), make_agent_project("octo/ledger")
        for agent_project in (first, second):
            await storage.create_agent_project(org, agent_project, ())
        renamed = first.model_copy(update={"name": "renamed"})
        assert await storage.write_agent_project(org, renamed, ())
        assert await storage.read_agent_project(org, first.id) == renamed
        ordered = sorted((renamed, second), key=lambda p: p.id)
        assert await storage.read_agent_projects(org, None, 10) == ordered
        assert await storage.read_agent_projects(org, ordered[0].id, 10) == ordered[1:]
        assert await storage.read_agent_projects(org, None, 1) == ordered[:1]

    async def test_an_agent_project_goes_only_while_no_sessions_row_names_it(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org = new_id()
        held, free = make_agent_project(), make_agent_project("octo/ledger")
        for agent_project in (held, free):
            await storage.create_agent_project(org, agent_project, ())
        await storage.bind_session(org, make_binding(new_id(), held.id))
        assert not await storage.delete_agent_project(org, held.id, ())
        assert await storage.read_agent_project(org, held.id) == held
        assert await storage.delete_agent_project(org, free.id, ())
        assert await storage.read_agent_project(org, free.id) is None
        assert not await storage.delete_agent_project(org, free.id, ())
        assert not await storage.write_agent_project(org, free, ())
        assert await storage.read_agent_project(org, free.id) is None

    async def test_a_sessions_agent_project_is_written_once_and_never_moves(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        first, second = make_agent_project(), make_agent_project("octo/ledger")
        for agent_project in (first, second):
            await storage.create_agent_project(org, agent_project, ())
        bound = make_binding(session, first.id)
        assert await storage.bind_session(org, bound) == bound
        assert await storage.bind_session(org, make_binding(session, second.id)) == bound
        assert await storage.read_binding(org, session) == bound
        assert await storage.read_binding(org, new_id()) is None

    async def test_another_tenant_naming_an_agent_project_or_a_session_reaches_none_of_it(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        """An agent project and a session's row are their tenant's: another tenant
        that names them reads nothing, writes nothing over them, and purges
        none of them. A row that presents the holder's id is refused."""
        org_a, org_b, session = new_id(), new_id(), new_id()
        agent_project = make_agent_project()
        await storage.create_agent_project(org_a, agent_project, ())
        bound = make_binding(session, agent_project.id)
        await storage.bind_session(org_a, bound)
        assert await storage.read_agent_project(org_b, agent_project.id) is None
        assert not await storage.create_agent_project(
            org_b, agent_project.model_copy(update={"name": "taken"}), ()
        )
        assert await storage.read_binding(org_b, session) is None
        with pytest.raises(TenantMismatch):
            await storage.bind_session(org_b, make_binding(session, new_id()))
        assert not await storage.purge_session(org_b, session)
        assert await storage.purge_tenant(org_b, 10) == 0
        assert await storage.read_agent_projects(org_b, None, 10) == []
        assert not await storage.write_agent_project(
            org_b, agent_project.model_copy(update={"name": "taken"}), ()
        )
        free = make_agent_project("octo/ledger")
        await storage.create_agent_project(org_a, free, ())
        assert not await storage.delete_agent_project(org_b, free.id, ())
        assert await storage.read_agent_project(org_a, free.id) == free
        assert await storage.read_agent_project(org_a, agent_project.id) == agent_project
        assert await storage.read_binding(org_a, session) == bound

    async def test_a_sessions_purge_takes_its_row_alone(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org, session, other = new_id(), new_id(), new_id()
        agent_project = make_agent_project()
        await storage.create_agent_project(org, agent_project, ())
        for each in (session, other):
            await storage.bind_session(org, make_binding(each, agent_project.id))
        assert await storage.purge_session(org, session)
        assert not await storage.purge_session(org, session)
        assert await storage.read_binding(org, session) is None
        assert await storage.read_binding(org, other) is not None
        assert await storage.read_agent_project(org, agent_project.id) == agent_project

    async def test_a_tenants_purge_takes_its_rows_alone_sessions_first(
        self, storage: AgentProjectStorageInterface
    ) -> None:
        org, other = new_id(), new_id()
        kept = make_agent_project()
        await storage.create_agent_project(other, kept, ())
        await storage.bind_session(other, make_binding(new_id(), kept.id))
        agent_project = make_agent_project()
        await storage.create_agent_project(org, agent_project, ())
        sessions = [new_id(), new_id()]
        for session in sessions:
            await storage.bind_session(org, make_binding(session, agent_project.id))
        assert await storage.purge_tenant(org, 2) == 2
        assert all([await storage.read_binding(org, s) is None for s in sessions])
        assert await storage.read_agent_project(org, agent_project.id) == agent_project
        assert await storage.purge_tenant(org, 2) == 1
        assert await storage.read_agent_project(org, agent_project.id) is None
        assert await storage.purge_tenant(org, 2) == 0
        assert await storage.read_agent_project(other, kept.id) == kept
