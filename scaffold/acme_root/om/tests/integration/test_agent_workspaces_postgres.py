"""The workspaces over Postgres, as a process wires them: an agent project's
allowlist lands with the rows that announce it, a session pins it as it is
created and its egress is read off that pin, a host that cannot give the
pinned level parks the loop on the resource, and the work a loop left is
kept, recorded, and told to the next loop."""

from collections.abc import AsyncIterator
from ipaddress import ip_address
from pathlib import Path

import pytest
from contracts.agent_workspaces import AgentProjectsTwin, GitTwin, ReaderTwin
from contracts.loops import ASSISTANT, reply, said
from contracts.platform_loops import platform_loop_over

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agent_workspaces.impl.manager import CREATED
from acme.om.agent_workspaces.types.egress import (
    EgressAllowlist,
    EgressMethod,
    EgressRequest,
    EgressRule,
)
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductAbsentImpl
from acme.om.platform_root import PlatformRootOptions, build_platform_managers
from acme.om.steps.types.header import LoopOutcome, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")
TWINNED = ASSISTANT.model_copy(
    update={
        "name": "twinned",
        "isolation": IsolationSpec(
            mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.OPEN)
        ),
    }
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


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_platform_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


async def test_a_session_pins_its_agent_projects_allowlist_and_its_egress_is_read_off_the_pin(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    agent_projects = AgentProjectsTwin()
    loop = platform_loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        kinds=(TWINNED,),
        platform=PlatformRootOptions(workspace_agent_projects=agent_projects),
    )
    workspaces = loop.platform.agent_workspaces
    listed = EgressAllowlist(
        id=new_id(),
        created_at=loop.clock(),
        updated_at=loop.clock(),
        created_by=owner.user_id,
        updated_by=owner.user_id,
        agent_project_id=agent_projects.agent_project_id,
        rules=(EgressRule(destination="git.example.com", methods=(EgressMethod.GET,)),),
    )
    await workspaces.write_allowlist(owner, listed)
    session_id = await loop.start("twinned")

    pinned = await workspaces.get_workspace(owner, session_id)
    assert (pinned.agent_project_id, pinned.egress) == (
        agent_projects.agent_project_id,
        EgressMode.ALLOWLIST,
    )
    events = await loop.managers.events.get_events(owner, 0, 100)
    assert CREATED in {event.kind for event in events}, "the write was announced"

    def ask(address: str, method: EgressMethod) -> EgressRequest:
        return EgressRequest(
            destination="git.example.com", address=ip_address(address), port=443, method=method
        )

    assert (
        await workspaces.egress(owner, session_id, ask("93.184.215.14", EgressMethod.GET))
    ).allowed
    refused = [
        ask("93.184.215.14", EgressMethod.POST),
        ask("169.254.169.254", EgressMethod.GET),
        ask("10.1.2.3", EgressMethod.GET),
    ]
    for request in refused:
        assert not (await workspaces.egress(owner, session_id, request)).allowed


async def test_a_host_that_cannot_give_the_pin_parks_the_loop_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    loop = platform_loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        kinds=(TWINNED,),
        environment="production",
        # Outside `local` a root refuses the null result gate.
        result_gate=ResultGateEvidenceImpl(
            storage.get_evidence_storage(),
            WorkProductAbsentImpl(),
            SessionAgentProjectsBoundImpl(storage.get_agent_project_storage()),
        ),
    )
    session_id = await loop.start("twinned")
    await loop.say(session_id, "Answer it.")
    loop.anthropic.add(reply(said("Never asked.")))

    run = await loop.loops.run(owner, session_id)

    assert run.end is RunEnd.PARKED and run.park is not None
    assert run.park.reason is ParkReason.RESOURCE and loop.anthropic.calls == []
    session = await loop.managers.agent_sessions.get_session(owner, session_id)
    assert session.park is not None and session.park.reason is ParkReason.RESOURCE


async def test_the_work_a_loop_left_is_recorded_and_told_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    git = GitTwin()
    loop = platform_loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        kinds=(TWINNED,),
        platform=PlatformRootOptions(
            workspace_agent_projects=AgentProjectsTwin(),
            workspace_git=git,
            workspace_reader=ReaderTwin(),
        ),
    )
    session_id = await loop.start("twinned")
    for text, leaves_work in (("First.", False), ("Second.", True), ("Third.", False)):
        git.dirty = leaves_work
        await loop.say(session_id, text)
        loop.anthropic.add(reply(said("Done.")))
        assert (await loop.loops.run(owner, session_id)).outcome is LoopOutcome.SUCCEEDED

    (kept,) = list(git.pushed)
    held = await loop.platform.agent_workspaces.get_workspace(owner, session_id)
    assert held.snapshot_ref == kept and held.notices == () and held.version > 1
    told = [s for s in await loop.history(session_id) if s.type is StepType.ENVIRONMENT_CHANGED]
    assert len(told) == 1 and kept in told[0].as_text()
