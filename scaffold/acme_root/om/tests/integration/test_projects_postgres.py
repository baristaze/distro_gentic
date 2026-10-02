"""Projects over Postgres, read the way a database reader reads it: the rows
of the projects and of each session's project, under a tenant's own scope
and the runtime login.

A session is created only under a project of its own tenant: another
tenant's project starts nothing and leaves no row, and another tenant
reads no row of it. A session's project never changes: a start under
another project is refused, and the runtime login may not rewrite or remove
the row. The one repository a session's work product lands on is its own
project's, and a project's retention narrowing reaches its sessions'
snapshot rows."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.project_storage import make_project
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Spawn, Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.exceptions import NotFound
from acme.om.projects.exceptions import ProjectFixed
from acme.om.projects.types.project import Project
from acme.om.retention.types.policy import ProjectRetention, RetentionPolicy
from acme.om.root import Managers, build_managers
from acme.om.storage.impl.pg_base import LoginSessions, set_scope
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.roles import DatabaseRole
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")
DELIVERY = AgentKind(
    name="delivery",
    version=1,
    tools=("read_log", "push_branch", "spawn", "submit"),
    done_rule=DoneRule.RESULT_TOOL,
    result_tool="submit",
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=2, count=2),
)


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


@pytest.fixture
def managers(storage: StoragePostgresImpl, tmp_path: Path) -> Managers:
    return build_managers(storage, InfraLocalImpl(tmp_path), agent_kinds=(DELIVERY,))


async def an_org(managers: Managers) -> TenantContext:
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
    )
    return owner


async def a_project(managers: Managers, ctx: TenantContext, path: str = "octo/reports") -> Project:
    return await managers.projects.create_project(ctx, make_project(path))


def a_start() -> Start:
    return Start(id=new_id(), kind="delivery", title="the weekly report is missing a total")


async def rows(
    pg_sessions: LoginSessions, statement: str, org_id: UUID, **values: Any
) -> list[dict[str, Any]]:
    """What a reader of the database sees, under the tenant's own scope."""
    async with pg_sessions[DatabaseRole.CORE]() as session:
        await set_scope(session, org_id, None, None)
        result = await session.execute(text(statement), {"org": org_id, **values})
        return [dict(row) for row in result.mappings()]


async def session_rows(pg_sessions: LoginSessions, org_id: UUID, session_id: UUID) -> list[dict]:
    return await rows(
        pg_sessions,
        "SELECT org_id, project_id FROM core.session_projects WHERE id = :session",
        org_id,
        session=session_id,
    )


async def test_a_session_is_created_only_under_a_project_of_its_own_tenant(
    managers: Managers, pg_sessions: LoginSessions
) -> None:
    ours, theirs = await an_org(managers), await an_org(managers)
    project = await a_project(managers, ours)
    stolen = a_start()
    with pytest.raises(NotFound):
        await managers.projects.start_session(theirs, project.id, stolen)
    with pytest.raises(NotFound):
        await managers.agent_sessions.get_session(theirs, stolen.id)
    for tenant in (ours, theirs):
        assert await session_rows(pg_sessions, tenant.org_id, stolen.id) == []

    session = await managers.projects.start_session(ours, project.id, a_start())
    assert await session_rows(pg_sessions, ours.org_id, session.id) == [
        {"org_id": ours.org_id, "project_id": project.id}
    ]
    assert await session_rows(pg_sessions, theirs.org_id, session.id) == []
    assert await rows(pg_sessions, "SELECT id FROM core.projects", theirs.org_id) == []
    assert await managers.projects.project_of(theirs, session.id) is None
    assert await managers.projects.project_of(ours, session.id) == project


async def test_a_sessions_project_never_changes(
    managers: Managers, pg_sessions: LoginSessions
) -> None:
    ctx = await an_org(managers)
    first, second = await a_project(managers, ctx), await a_project(managers, ctx, "octo/ledger")
    start = a_start()
    session = await managers.projects.start_session(ctx, first.id, start)
    with pytest.raises(ProjectFixed):
        await managers.projects.start_session(ctx, second.id, start)
    spawn = Spawn(id=new_id(), kind="delivery", title="reproduce it", objective="run it")
    child = await managers.agents.spawn(ctx, session.id, spawn)
    for each in (session.id, child.id):
        assert await session_rows(pg_sessions, ctx.org_id, each) == [
            {"org_id": ctx.org_id, "project_id": first.id}
        ]
    for statement in (
        "UPDATE core.session_projects SET project_id = :project WHERE id = :session",
        "DELETE FROM core.session_projects WHERE id = :session",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            await rows(pg_sessions, statement, ctx.org_id, project=second.id, session=session.id)
    assert await managers.projects.project_of(ctx, session.id) == first


async def test_only_the_bound_repository_is_work_product(managers: Managers) -> None:
    ctx, other = await an_org(managers), await an_org(managers)
    reports, ledger = await a_project(managers, ctx), await a_project(managers, ctx, "octo/ledger")
    on_reports = await managers.projects.start_session(ctx, reports.id, a_start())
    on_ledger = await managers.projects.start_session(ctx, ledger.id, a_start())
    loose = await managers.agents.start_session(ctx, a_start())
    work = managers.projects.work_repository
    assert await work(ctx, on_reports.id) == reports.repository != ledger.repository
    assert await work(ctx, on_ledger.id) == ledger.repository
    assert await work(ctx, loose.id) is None
    assert await work(other, on_reports.id) is None


async def test_a_projects_retention_narrowing_reaches_its_sessions(
    managers: Managers, pg_sessions: LoginSessions
) -> None:
    ctx = await an_org(managers)
    narrow, other = await a_project(managers, ctx), await a_project(managers, ctx, "octo/ledger")
    week = timedelta(days=7)
    current = await managers.retention.get_policy(ctx)
    narrowing = ProjectRetention(
        project_id=narrow.id, policy=RetentionPolicy(content_lifetime=week)
    )
    await managers.retention.write_policy(
        ctx, current.model_copy(update={"projects": (narrowing,)})
    )
    on_narrow = await managers.projects.start_session(ctx, narrow.id, a_start())
    on_other = await managers.projects.start_session(ctx, other.id, a_start())
    snapshots = await rows(
        pg_sessions,
        "SELECT session_id, project_id, policy->>'content_lifetime' AS content"
        " FROM core.session_retention ORDER BY session_id",
        ctx.org_id,
    )
    assert snapshots == [
        {"session_id": on_narrow.id, "project_id": narrow.id, "content": "P7D"},
        {"session_id": on_other.id, "project_id": other.id, "content": None},
    ]
