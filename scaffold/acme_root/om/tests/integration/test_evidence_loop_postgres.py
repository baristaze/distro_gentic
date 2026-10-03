"""A delivery agent's loop over Postgres, ended through the evidence gate:
a success with no validation at its head goes back to the model refused,
and once the executor has validated that head, the same claim ends the
loop succeeded and verified."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from contracts.evidence import ScriptedExecutor, checkout_policy, delivered
from contracts.evidence_storage import make_record
from contracts.loops import loop_over, reply, said
from contracts.project_storage import in_project
from contracts.tools import result_text

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext, TenantContext
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductMemoryImpl
from acme.om.evidence.types.record import RunPurpose
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.root import build_managers
from acme.om.steps.types.content import ToolUseBlock
from acme.om.steps.types.header import AcceptedResult, LoopOutcome, ToolResponseHeader
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")


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


def submit(claim: str, *evidence: UUID) -> ToolUseBlock:
    return ToolUseBlock(
        id=f"use_submit_{new_id().hex[:8]}",
        name="submit",
        input={"claim": claim, "evidence": [str(found) for found in evidence]},
    )


async def test_a_loop_ends_succeeded_only_once_its_head_is_validated(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    work = WorkProductMemoryImpl()
    loop = loop_over(
        tmp_path,
        storage=storage,
        owner=owner,
        result_gate=ResultGateEvidenceImpl(
            storage.get_evidence_storage(),
            work,
            SessionProjectsBoundImpl(storage.get_project_storage()),
        ),
        executor=ScriptedExecutor(),
        work_product=work,
    )
    evidence = loop.managers.evidence
    session_id = await loop.start("delivery")
    project = await in_project(storage.get_project_storage(), owner.org_id, session_id)
    await evidence.write_policy(owner, checkout_policy(project=project))
    run = make_record(session_id, step_id=new_id())
    await evidence.record_run(owner, run)
    work.deliver(owner.org_id, session_id, delivered())

    # No validation at the head: the success goes back refused, and the
    # model concludes it cannot show it.
    await loop.say(session_id, "Fix the cart.")
    loop.anthropic.add(
        reply(said("Fixed."), submit("succeeded", run.id)),
        reply(said("I cannot show it yet."), submit("failed", run.id)),
    )
    first = await loop.loops.run(owner, session_id)
    assert (first.end, first.outcome) == (RunEnd.ENDED, LoopOutcome.FAILED)
    answers = [s for s in await loop.history(session_id) if s.type is StepType.TOOL_RESPONSE]
    assert "no validation ran at the head c0ffee" in result_text(answers[0])

    # Validated at the head by the executor: the same claim succeeds, verified.
    await evidence.validate(owner, session_id, RunPurpose.VALIDATION)
    await loop.say(session_id, "Validation ran. Submit again.")
    loop.anthropic.add(reply(said("Submitting."), submit("succeeded", run.id)))
    second = await loop.loops.run(owner, session_id)
    assert (second.end, second.outcome) == (RunEnd.ENDED, LoopOutcome.SUCCEEDED)
    last = [s for s in await loop.history(session_id) if s.type is StepType.TOOL_RESPONSE][-1]
    header = last.header
    assert isinstance(header, ToolResponseHeader)
    assert header.accepted == AcceptedResult(outcome=LoopOutcome.SUCCEEDED, verified=True)
