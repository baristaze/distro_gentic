"""The platform's agents over Postgres: the assistant answers from its
corpus with a citation, a call it makes to a shell is refused, and its
draft leaves the live policy as it was; the engineer starts two sub-agents,
wakes on each report, and ends, its tree within its root's budget; a
validation session is the platform's own work, run on the executor and
finished with its execution record, with no model call."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from contracts.loops import reply, said
from contracts.platform_agents import (
    an_engineer_starts_two_sub_agents_and_wakes_on_each_report,
    calls,
    platform_over,
    sub_agents_over,
)

from acme.om.base import new_id
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.evidence.rules import policy_key
from acme.om.platform_agents import kinds
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.steps.types.header import LoopOutcome, ToolFailure
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.work.types.work_item import WorkKind

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")
WORKER = AppContext(type=AppType.WORKER, version="worker@test")


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


async def test_the_assistant_over_postgres_cites_its_corpus_and_reaches_no_shell(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    platform = platform_over(tmp_path, storage=storage)
    slug = f"ajax-{new_id().hex[-8:]}"
    platform.owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
    )
    session_id = await platform.start(kinds.PLATFORM_ASSISTANT)
    await platform.say(session_id, "Why is my session waiting? Run the queue report.")
    platform.anthropic.add(
        reply(
            said("Let me look."),
            calls(kinds.SEARCH_CORPUS, "use_search", query="why a session waits"),
            calls(kinds.RUN_COMMAND, "use_shell", argv=["queue-report"]),
            calls(
                kinds.DRAFT_TOOL_POLICY,
                "use_draft",
                rules=[{"authorization_class": "execute", "decision": "allow"}],
            ),
        ),
        reply(said("It waits for its tenant's share (om/README.md, Why a session waits).")),
    )

    run = await platform.managers.loop.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(session_id, "use_search")
    best = json.loads(text)["passages"][0]
    assert failure is None
    assert (best["path"], best["heading"]) == ("om/README.md", "Why a session waits")
    failure, text = await platform.answer(session_id, "use_shell")
    assert failure is ToolFailure.INVALID_INPUT and "no tool named 'run_command'" in text
    failure, text = await platform.answer(session_id, "use_draft")
    assert failure is None and json.loads(text)["valid"] is True
    assert (await platform.managers.tools.get_policy(platform.owner)).rules == ()


async def test_the_engineer_starts_two_sub_agents_and_wakes_on_each_report_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    platform, executor, work = sub_agents_over(tmp_path, storage=storage)
    slug = f"ajax-{new_id().hex[-8:]}"
    platform.owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
    )
    await an_engineer_starts_two_sub_agents_and_wakes_on_each_report(platform, executor, work)


async def test_a_validation_session_over_postgres_is_platform_work_with_no_model_call(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    platform = platform_over(tmp_path, storage=storage, executor=executor)
    slug = f"ajax-{new_id().hex[-8:]}"
    platform.owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), "Ajax", slug, f"ann-{slug}@x.test", "Ann"
    )
    project_id = new_id()
    await platform.managers.evidence.write_policy(
        platform.owner, make_policy(policy_key(project_id))
    )
    validations = platform.managers.platform_agents
    start = ValidationStart(
        id=new_id(), project_id=project_id, check_name="unit", head="c" * 40, base="b" * 40
    )

    session = await validations.start_validation(platform.owner, start)

    claimed = await platform.managers.work.claim(
        RequestContext(request_id=new_id(), app=WORKER),
        "default",
        (WorkKind.VALIDATION,),
        "maintenance-1",
        timedelta(seconds=30),
    )
    assert claimed is not None
    ctx, item = claimed
    assert (item.kind, item.target_id) == (WorkKind.VALIDATION, session.id)
    finished = await validations.run_validation(ctx, session.id)
    await platform.managers.work.complete(ctx, item)

    stored = await validations.get_validation(platform.owner, session.id)
    (record,) = (await platform.managers.evidence.get_runs(ctx, session.id, None, 10)).items
    assert stored == finished
    assert (stored.status, stored.run_id) == (ValidationStatus.FINISHED, record.id)
    assert platform.model_calls() == 0
