"""Agent projects over the memory storage: an agent project is its tenant's and binds one
repository; a session started under one belongs to it from its creation,
and so do the sessions it spawns and hands over; nothing moves a session to
another agent project; and the one repository a session's work product lands on
is its agent project's."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agent_projects.exceptions import AgentProjectFixed
from acme.om.agent_projects.types.agent_project import AgentProject, Repository
from acme.om.agent_root import AgentRootOptions
from acme.om.agent_sessions.impl.manager import AgentSessionsOptions
from acme.om.agents.types.kind import AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Handoff, Spawn, Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id
from acme.om.context import Role, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, TenantMismatch
from acme.om.platform_root import PlatformManagers, build_platform_managers
from acme.om.retention.types.policy import AgentProjectRetention, RetentionPolicy
from acme.om.spend_budgets.types.amount import Amount
from acme.om.storage.impl.memory import StorageMemoryImpl

from contracts.agent_project_storage import make_agent_project
from contracts.agent_step_storage import make_message
from contracts.doubles import context, model_request
from contracts.factories import make_org
from contracts.tools import stand_ins

DELIVERY = AgentKind(
    name="delivery",
    version=1,
    tools=("read_log", "push_branch", "spawn", "submit"),
    done_rule=DoneRule.RESULT_TOOL,
    result_tool="submit",
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=2, count=2),
    share=Amount(cost_micros=5_000),
)
ASSISTANT = AgentKind(
    name="assistant",
    version=1,
    tools=("read_records",),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.DELEGATED,
    tree=TreeLimits(height=1, count=0),
)
TOOLS = stand_ins(*DELIVERY.tools, *ASSISTANT.tools)


@pytest.fixture
def managers(tmp_path: Path) -> PlatformManagers:
    return build_platform_managers(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        agent_root_options=AgentRootOptions(agent_kinds=(DELIVERY, ASSISTANT), tool_catalog=TOOLS),
    )


def a_start(kind: str = "delivery") -> Start:
    return Start(id=new_id(), kind=kind, title="the weekly report is missing a total")


async def an_agent_project(
    managers: PlatformManagers, ctx: TenantContext, path: str = "octo/reports"
) -> AgentProject:
    return await managers.agent_projects.create_agent_project(ctx, make_agent_project(path))


async def test_an_agent_project_is_its_tenants_and_written_by_who_configures_it(
    managers: PlatformManagers,
) -> None:
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    with pytest.raises(NotAuthorized):
        await an_agent_project(managers, member)
    agent_project = await an_agent_project(managers, admin)
    assert agent_project.created_by == admin.user_id
    assert (
        await managers.agent_projects.get_agent_project(member, agent_project.id) == agent_project
    )
    asked = agent_project.model_copy(update={"name": "renamed"})
    assert await managers.agent_projects.create_agent_project(admin, asked) == agent_project, (
        "made once"
    )
    stranger = context(Role.OWNER)
    with pytest.raises(NotFound):
        await managers.agent_projects.get_agent_project(stranger, agent_project.id)
    with pytest.raises(TenantMismatch):
        await managers.agent_projects.create_agent_project(stranger, asked)


def test_a_repository_is_one_value_in_any_case_and_a_bad_one_is_refused() -> None:
    assert Repository(host="GitHub.com", path="Octo/Reports") == Repository(
        host="github.com", path="octo/reports"
    )
    for host, path in (
        ("github.com", "reports"),
        ("github.com", "octo/../reports"),
        ("github.com", "/octo/reports"),
        ("localhost", "octo/reports"),
        ("github.com", "octo/reports/"),
    ):
        with pytest.raises(ValidationError):
            Repository(host=host, path=path)


async def test_a_session_started_under_an_agent_project_belongs_to_it(
    managers: PlatformManagers,
) -> None:
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    agent_project = await an_agent_project(managers, admin)
    session = await managers.agent_projects.start_agent_session(member, agent_project.id, a_start())
    assert await managers.agent_projects.agent_project_of(member, session.id) == agent_project
    assert (
        await managers.agent_projects.work_repository(member, session.id)
        == agent_project.repository
    )
    started = await managers.agents.start_agent_session(member, a_start())
    assert await managers.agent_projects.agent_project_of(member, started.id) is None, (
        "of no agent project"
    )
    assert await managers.agent_projects.work_repository(member, started.id) is None


async def test_another_tenants_agent_project_starts_nothing(managers: PlatformManagers) -> None:
    """A session is created only under an agent project of its own tenant: another
    tenant's agent project is not found, and no session and no row are left."""
    theirs = await an_agent_project(managers, context(Role.ADMIN))
    ours = context(Role.MEMBER)
    start = a_start()
    with pytest.raises(NotFound):
        await managers.agent_projects.start_agent_session(ours, theirs.id, start)
    with pytest.raises(NotFound):
        await managers.agent_sessions.get_agent_session(ours, start.id)
    assert await managers.agent_projects.agent_project_of(ours, start.id) is None


async def test_a_sessions_agent_project_never_moves(managers: PlatformManagers) -> None:
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    first, second = (
        await an_agent_project(managers, admin),
        await an_agent_project(managers, admin, "octo/ledger"),
    )
    start = a_start()
    session = await managers.agent_projects.start_agent_session(member, first.id, start)
    assert await managers.agent_projects.start_agent_session(member, first.id, start) == session
    with pytest.raises(AgentProjectFixed):
        await managers.agent_projects.start_agent_session(member, second.id, start)
    assert await managers.agent_projects.agent_project_of(member, session.id) == first
    # A session started under no agent project stays under none.
    loose = await managers.agents.start_agent_session(member, a_start())
    with pytest.raises(AgentProjectFixed):
        await managers.agent_projects.start_agent_session(
            member, second.id, a_start().model_copy(update={"id": loose.id})
        )
    assert await managers.agent_projects.agent_project_of(member, loose.id) is None


async def test_a_spawned_or_handed_over_session_belongs_where_it_came_from(
    managers: PlatformManagers,
) -> None:
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    agent_project = await an_agent_project(managers, admin)
    parent = await managers.agent_projects.start_agent_session(member, agent_project.id, a_start())
    spawn = Spawn(id=new_id(), kind="delivery", title="reproduce it", objective="run it")
    child = await managers.agents.spawn(member, parent.id, spawn)
    assert await managers.agent_projects.agent_project_of(member, child.id) == agent_project
    source = await managers.agent_projects.start_agent_session(
        member, agent_project.id, a_start("assistant")
    )
    (said,) = await managers.agent_steps.append_inputs(member, source.id, [make_message(source.id)])
    await model_request(managers, member, source.id, [said])
    handoff = Handoff(id=new_id(), kind="delivery", title="fix it", objective="fix the drop")
    handed = await managers.agents.hand_off(member, source.id, handoff)
    assert await managers.agent_projects.agent_project_of(member, handed.id) == agent_project


async def test_a_child_of_no_agent_project_takes_none_named_for_it(
    managers: PlatformManagers,
) -> None:
    """A session spawned from one of no agent project belongs to none, even when an
    agent project row was written under its id before it was made."""
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    agent_project = await an_agent_project(managers, admin)
    parent = await managers.agents.start_agent_session(member, a_start())
    spawn = Spawn(id=new_id(), kind="delivery", title="reproduce it", objective="run it")
    with pytest.raises(NotFound):
        # A start that fails after the row is written leaves the row.
        await managers.agent_projects.start_agent_session(
            member, agent_project.id, Start(id=spawn.id, kind="reviewer", title="never made")
        )
    with pytest.raises(AgentProjectFixed):
        await managers.agents.spawn(member, parent.id, spawn)


async def test_an_agent_projects_retention_narrowing_reaches_its_sessions(
    managers: PlatformManagers,
) -> None:
    """Retention asks the agent projects which agent project a new session belongs to:
    a session of the narrowing agent project, and the child it spawns, take the
    narrowing; one of a sibling agent project, or of none, takes its tenant's
    policy alone."""
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    narrow, other = (
        await an_agent_project(managers, admin),
        await an_agent_project(managers, admin, "octo/ledger"),
    )
    tenant, week = RetentionPolicy(content_lifetime=timedelta(days=30)), timedelta(days=7)
    current = await managers.retention.get_policy(admin)
    narrowing = AgentProjectRetention(
        agent_project_id=narrow.id, policy=RetentionPolicy(content_lifetime=week)
    )
    await managers.retention.write_policy(
        admin, current.model_copy(update={"policy": tenant, "agent_projects": (narrowing,)})
    )
    on_narrow = await managers.agent_projects.start_agent_session(member, narrow.id, a_start())
    spawn = Spawn(id=new_id(), kind="delivery", title="reproduce it", objective="run it")
    child = await managers.agents.spawn(member, on_narrow.id, spawn)
    on_other = await managers.agent_projects.start_agent_session(member, other.id, a_start())
    loose = await managers.agents.start_agent_session(member, a_start())
    snapshot = managers.retention.get_snapshot
    for session in (on_narrow, child):
        taken = await snapshot(member, session.id)
        assert (taken.agent_project_id, taken.policy.content_lifetime) == (narrow.id, week)
    assert (await snapshot(member, on_other.id)).policy == tenant
    assert (await snapshot(member, loose.id)).policy == tenant


async def test_only_the_bound_repository_is_work_product(managers: PlatformManagers) -> None:
    """Each session's work product lands on its own agent project's repository:
    never on a sibling agent project's, never on another tenant's, and never on
    any for a session of no agent project."""
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    reports, ledger = (
        await an_agent_project(managers, admin),
        await an_agent_project(managers, admin, "octo/ledger"),
    )
    on_reports = await managers.agent_projects.start_agent_session(member, reports.id, a_start())
    on_ledger = await managers.agent_projects.start_agent_session(member, ledger.id, a_start())
    loose = await managers.agents.start_agent_session(member, a_start())
    work = managers.agent_projects.work_repository
    assert await work(member, on_reports.id) == Repository(host="github.com", path="OCTO/reports")
    assert await work(member, on_reports.id) != ledger.repository
    assert await work(member, on_ledger.id) == ledger.repository
    assert await work(member, loose.id) is None
    assert await work(context(Role.OWNER), on_reports.id) is None, "another tenant's is none"


async def test_a_sessions_row_goes_with_its_purge_and_a_living_tenant_keeps_all(
    tmp_path: Path,
) -> None:
    managers = build_platform_managers(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        agent_root_options=AgentRootOptions(
            agent_kinds=(DELIVERY,),
            tool_catalog=TOOLS,
            agent_sessions_options=AgentSessionsOptions(retention=timedelta(0)),
        ),
    )
    org = make_org()
    admin, member = context(Role.ADMIN, org), context(Role.MEMBER, org)
    agent_project = await an_agent_project(managers, admin)
    gone = await managers.agent_projects.start_agent_session(member, agent_project.id, a_start())
    kept = await managers.agent_projects.start_agent_session(member, agent_project.id, a_start())
    assert await managers.agent_projects.purge_tenant(member) == 0, "a living tenant keeps its rows"
    await managers.agent_sessions.delete_agent_session(member, gone.id)
    assert await managers.agent_sessions.purge_across_tenants() == 1
    assert await managers.agent_projects.agent_project_of(member, gone.id) is None, (
        "it went with its session"
    )
    assert not await managers.agent_projects.purge_agent_session(member.org_id, gone.id)
    assert await managers.agent_projects.agent_project_of(member, kept.id) == agent_project
