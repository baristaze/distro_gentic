"""A validation session as the worker runs it: its item is claimed from
the platform's own lane and handled by the worker's own handler, which
runs the check on the executor once and finishes the session with the
record it wrote. A check its project's policy does not declare fails for
good."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy
from worker_support import request, sign_in

from acme.infra.impl.local import InfraLocalImpl
from acme.om.base import new_id
from acme.om.context import TenantContext
from acme.om.evidence.rules import policy_key
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.root import PlatformPorts
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.work.types.handler import WorkRefused
from acme.om.work.types.work_item import WorkItem, WorkKind
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop

LEASE = timedelta(seconds=30)
HEAD = "c" * 40
BASE = "b" * 40


async def started(container: WorkerContainer, ctx: TenantContext, check: str) -> UUID:
    project_id = new_id()
    await container.managers.evidence.write_policy(ctx, make_policy(policy_key(project_id)))
    session = await container.managers.platform_agents.start_validation(
        ctx,
        ValidationStart(id=new_id(), project_id=project_id, check_name=check, head=HEAD, base=BASE),
    )
    return session.id


async def claimed(container: WorkerContainer) -> tuple[TenantContext, WorkItem]:
    found = await container.managers.work.claim(
        request(), "default", (WorkKind.VALIDATION,), "maintenance-test", LEASE
    )
    assert found is not None
    return found


# Check 2: a validation session is platform work, which the worker's own
# handler runs to its execution record.


async def test_the_worker_runs_a_validation_session_once_to_its_record(tmp_path: Path) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), ports=PlatformPorts(executor=executor)
    )
    owner = await sign_in(container)
    session_id = await started(container, owner, "unit")
    handler = build_loop(container)._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]

    ctx, item = await claimed(container)
    assert item.target_id == session_id
    await handler.handle(ctx, item)
    await handler.handle(ctx, item)

    finished = await container.managers.platform_agents.get_validation(owner, session_id)
    (record,) = (await container.managers.evidence.get_runs(owner, session_id, None, 10)).items
    assert (finished.status, finished.run_id) == (ValidationStatus.FINISHED, record.id)
    assert len(executor.requests) == 1, "handled again, it runs nothing"


async def test_a_check_its_policy_does_not_declare_fails_for_good(tmp_path: Path) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), ports=PlatformPorts(executor=executor)
    )
    owner = await sign_in(container)
    await started(container, owner, "lint")
    handler = build_loop(container)._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]

    ctx, item = await claimed(container)
    with pytest.raises(WorkRefused, match="declares no check lint"):
        await handler.handle(ctx, item)
    assert executor.requests == []
