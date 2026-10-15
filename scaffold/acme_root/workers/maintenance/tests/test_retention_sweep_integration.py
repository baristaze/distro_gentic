"""The retention sweep over Postgres, as the worker runs it: its container
built from its settings, its loop's one pass. A session past its content's
life comes out of the pass with its content gone, its key destroyed by the
local key service, and the audit entry holding that service's report."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from worker_support import request

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.agent_step import Actor, AgentStepType, Origin, AgentStep
from acme.om.agent_steps.types.content import Content, ContentState, TextBlock
from acme.om.agent_steps.types.header import InputHeader
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id, utcnow
from acme.om.retention.impl.manager import KEY_DESTROYED
from acme.om.retention.types.policy import RetentionPolicy
from acme.workers.maintenance.container import WorkerContainer
from acme.workers.maintenance.main import build_loop
from acme.workers.maintenance.settings import MaintenanceSettings

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[WorkerContainer]:
    settings = MaintenanceSettings(
        cache_backend="memory",
        topics_backend="memory",
        buckets_backend="local",
        buckets_root=tmp_path / "buckets",
        queues_backend="memory",
        secrets_backend="local",
        keys_backend="memory",
        sentry_dsn=None,
        otel_endpoint=None,
        worker_id="retention-integration",
    )
    settings.refuse_remote()
    built = WorkerContainer.build(settings)
    yield built
    await built.close()


def a_session() -> AgentSession:
    now, by, agent_session_id = utcnow(), new_id(), new_id()
    return AgentSession(
        id=agent_session_id,
        created_at=now,
        updated_at=now,
        created_by=by,
        updated_by=by,
        title="a session past its content's life",
        kind="delivery",
        kind_version=1,
        root_id=agent_session_id,
    )


def a_message(agent_session_id: UUID, text: str) -> AgentStep:
    agent_step_id = new_id()
    return AgentStep(
        id=agent_step_id,
        created_at=utcnow(),
        agent_session_id=agent_session_id,
        loop_id=agent_step_id,
        type=AgentStepType.MESSAGE,
        actor=Actor.PERSON,
        origin=Origin.PORTAL,
        header=InputHeader(principal=Principal(kind=PrincipalKind.PERSON, id=new_id())),
        content=Content(blocks=(TextBlock(text=text),)),
    )


async def test_one_pass_destroys_an_expired_sessions_key_and_audits_the_report(
    container: WorkerContainer,
) -> None:
    managers = container.managers
    tail = new_id().hex[-8:]
    owner, _ = await managers.tenancy.bootstrap(
        request(), "Pump", f"pump-{tail}", f"pump-{tail}@example.test", "Pat"
    )
    current = await managers.retention.get_policy(owner)
    await managers.retention.write_policy(
        owner,
        current.model_copy(
            update={"policy": RetentionPolicy(content_lifetime=timedelta(milliseconds=1))}
        ),
    )
    session = await managers.agent_sessions.create_agent_session(owner, a_session())
    said = "the pump log shows a pressure spike at 14:02"
    await managers.agent_steps.append_inputs(owner, session.id, [a_message(session.id, said)])

    await build_loop(container)._sweep_once()  # pyright: ignore[reportPrivateUsage]

    steps = (await managers.agent_steps.get_agent_steps(owner, session.id, 0, 10)).items
    assert [step.content.state for step in steps] == [ContentState.ABSENT]
    (entry,) = [
        e for e in await managers.change_events.get_change_events(owner, 0, 100) if e.kind == KEY_DESTROYED
    ]
    assert entry.payload["reported"] is True
    assert entry.payload["service"] == "keys=local"
    snapshot = await managers.retention.get_snapshot(owner, session.id)
    assert snapshot.destruction is not None
    assert snapshot.destruction.receipt == entry.payload["receipt"]
