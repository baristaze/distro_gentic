"""A validation session as the worker runs it: its item is claimed from
the platform's own lane and handled by the worker's own handler, which
runs the check on the executor once and finishes the session with the
record it wrote. A check its agent project's policy no longer declares fails for
good, and its session reads refused with the reason; a check whose work
fails on its last attempt reads refused with the error's class, and its
item still fails for good."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import request, sign_in

from acme.infra.impl.local import InfraLocalImpl
from acme.om.base import new_id
from acme.om.context import TenantContext
from acme.om.evidence.rules import policy_key
from acme.om.evidence.types.validation import ExecutionRequest, ExecutorReport
from acme.om.platform_agents.types.validation import ValidationStart, ValidationStatus
from acme.om.platform_root import PlatformPorts, ProductKinds
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.work.types.handler import WorkRefused
from acme.om.work.types.work_item import WorkItem, WorkKind, WorkStatus
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop

from contracts.evidence import ScriptedExecutor
from contracts.evidence_storage import make_policy

LEASE = timedelta(seconds=30)
HEAD = "c" * 40
BASE = "b" * 40


class Unmade(ScriptedExecutor):
    """An executor whose instance is never made: every run fails, on no
    precondition, as one whose host cannot start an instance does."""

    async def run(self, ctx: TenantContext, request: ExecutionRequest) -> ExecutorReport:
        self.requests.append(request)
        raise ConnectionError("the instance at 10.0.0.7 could not be made")


async def started(
    container: WorkerContainer, ctx: TenantContext, check: str, executor: str | None = None
) -> UUID:
    agent_project_id = new_id()
    policy = make_policy(policy_key(agent_project_id))
    if executor is not None:
        moved = tuple(each.model_copy(update={"executor": executor}) for each in policy.checks)
        policy = policy.model_copy(update={"checks": moved})
    await container.managers.evidence.write_policy(ctx, policy)
    session = await container.managers.platform_agents.start_validation(
        ctx,
        ValidationStart(
            id=new_id(), agent_project_id=agent_project_id, check_name=check, head=HEAD, base=BASE
        ),
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
    agent_session_id = await started(container, owner, "unit")
    handler = build_loop(container)._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]

    ctx, item = await claimed(container)
    assert item.target_id == agent_session_id
    await handler.handle(ctx, item)
    await handler.handle(ctx, item)

    finished = await container.managers.platform_agents.get_validation(owner, agent_session_id)
    (record,) = (
        await container.managers.evidence.get_runs(owner, agent_session_id, None, 10)
    ).items
    assert (finished.status, finished.run_id) == (ValidationStatus.FINISHED, record.id)
    assert len(executor.requests) == 1, "handled again, it runs nothing"


async def test_a_check_its_policy_no_longer_declares_fails_for_good(tmp_path: Path) -> None:
    executor = ScriptedExecutor(capabilities=frozenset())
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), ports=PlatformPorts(executor=executor)
    )
    owner = await sign_in(container)
    agent_session_id = await started(container, owner, "unit")
    # The policy renames the check after the session started.
    session = await container.managers.platform_agents.get_validation(owner, agent_session_id)
    evidence = container.managers.evidence
    policy = await evidence.get_policy(owner, policy_key(session.agent_project_id))
    renamed = tuple(each.model_copy(update={"name": "lint"}) for each in policy.checks)
    await evidence.write_policy(
        owner, policy.model_copy(update={"checks": renamed, "requirements": ()})
    )
    handler = build_loop(container)._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]

    ctx, item = await claimed(container)
    with pytest.raises(WorkRefused, match="declares no check unit"):
        await handler.handle(ctx, item)
    with pytest.raises(WorkRefused, match="declares no check unit"):
        await handler.handle(ctx, item)

    refused = await container.managers.platform_agents.get_validation(owner, agent_session_id)
    assert refused.status is ValidationStatus.REFUSED
    assert refused.refusal == f"the agent project {session.agent_project_id} declares no check unit"
    assert executor.requests == []


async def test_a_check_naming_a_products_executor_runs_on_it(tmp_path: Path) -> None:
    platform, batch = (
        ScriptedExecutor(capabilities=frozenset()),
        ScriptedExecutor(name="batch-1", capabilities=frozenset()),
    )
    ports = PlatformPorts(executor=platform, kinds=ProductKinds(executors={"batch": batch}))
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), ports=ports
    )
    owner = await sign_in(container)
    agent_session_id = await started(container, owner, "unit", executor="batch")
    handler = build_loop(container)._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]

    ctx, item = await claimed(container)
    await handler.handle(ctx, item)
    (record,) = (
        await container.managers.evidence.get_runs(owner, agent_session_id, None, 10)
    ).items
    assert (len(batch.requests), platform.requests) == (1, [])
    assert record.executor == "batch-1"


async def test_a_check_whose_work_fails_on_its_last_attempt_reads_refused(
    tmp_path: Path,
) -> None:
    executor = Unmade(capabilities=frozenset())
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(), InfraLocalImpl(tmp_path), ports=PlatformPorts(executor=executor)
    )
    owner = await sign_in(container)
    agent_session_id = await started(container, owner, "unit")
    loop = build_loop(container)
    handler = loop._handlers[WorkKind.VALIDATION]  # pyright: ignore[reportPrivateUsage]
    sessions = container.managers.platform_agents

    ctx, item = await claimed(container)
    assert item.attempts < item.max_attempts
    with pytest.raises(ConnectionError):
        await handler.handle(ctx, item)
    waiting = await sessions.get_validation(owner, agent_session_id)
    assert waiting.status is ValidationStatus.QUEUED, "an attempt with more to come"

    # The last attempt, settled as the loop settles it.
    last = item.model_copy(update={"attempts": item.max_attempts})
    await loop._handle(ctx, last)  # pyright: ignore[reportPrivateUsage]

    refused = await sessions.get_validation(owner, agent_session_id)
    assert refused.status is ValidationStatus.REFUSED
    assert refused.refusal == "its check failed on its last attempt: ConnectionError"
    assert refused.run_id is None
    failed = await container.managers.work.get_item(owner, item.id)
    assert failed.status is WorkStatus.FAILED, "the item is still a dead letter"
    assert len(executor.requests) == 2
