"""The workspaces over Postgres, as a process wires them: a project's
allowlist lands with the rows that announce it, a session pins it as it is
created and its egress is read off that pin, a host that cannot give the
pinned level parks the loop on the resource, and the work a loop left is
kept, recorded, and told to the next loop."""

from collections.abc import AsyncIterator
from ipaddress import ip_address
from pathlib import Path

import pytest
from contracts.loops import ASSISTANT, loop_over, reply, said
from contracts.workspaces import GitTwin, ProjectsTwin

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductAbsentImpl
from acme.om.root import build_managers
from acme.om.steps.types.header import LoopOutcome, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.workspaces.impl.manager import CREATED
from acme.om.workspaces.types.egress import EgressAllowlist, EgressMethod, EgressRequest, EgressRule

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
    managers = build_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


async def test_a_session_pins_its_projects_allowlist_and_its_egress_is_read_off_the_pin(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    projects = ProjectsTwin()
    loop = loop_over(
        tmp_path, storage=storage, owner=owner, kinds=(TWINNED,), workspace_projects=projects
    )
    workspaces = loop.managers.workspaces
    listed = EgressAllowlist(
        id=new_id(),
        created_at=loop.clock(),
        updated_at=loop.clock(),
        created_by=owner.user_id,
        updated_by=owner.user_id,
        project_id=projects.project_id,
        rules=(EgressRule(destination="git.example.com", methods=(EgressMethod.GET,)),),
    )
    await workspaces.write_allowlist(owner, listed)
    session_id = await loop.start("twinned")

    pinned = await workspaces.get_workspace(owner, session_id)
    assert (pinned.project_id, pinned.egress) == (projects.project_id, EgressMode.ALLOWLIST)
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
    loop = loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        kinds=(TWINNED,),
        environment="production",
        # Outside `local` a root refuses the null result gate.
        result_gate=ResultGateEvidenceImpl(storage.get_evidence_storage(), WorkProductAbsentImpl()),
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
    git = GitTwin(dirty=True)
    loop = loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        kinds=(TWINNED,),
        workspace_projects=ProjectsTwin(),
        workspace_git=git,
    )
    session_id = await loop.start("twinned")
    for text in ("First.", "Second."):
        await loop.say(session_id, text)
        loop.anthropic.add(reply(said("Done.")))
        assert (await loop.loops.run(owner, session_id)).outcome is LoopOutcome.SUCCEEDED

    first, second = list(git.pushed)
    held = await loop.managers.workspaces.get_workspace(owner, session_id)
    assert held.snapshot_ref == second and held.version > 1
    told = [s for s in await loop.history(session_id) if s.type is StepType.ENVIRONMENT_CHANGED]
    assert len(told) == 1 and first in told[0].as_text()
