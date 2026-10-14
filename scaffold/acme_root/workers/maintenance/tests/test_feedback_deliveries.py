"""The feedback deliveries: an event an integration verified is routed and
fires the agent automations it matches once, at the text cap too, and an
agent automation outside a local stack starts in an agent project."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from test_deliveries import consumer_of, depth, queued
from worker_support import build_container, sign_in

from acme.om.agent_automations.types.agent_automation import (
    Action,
    ActionKind,
    AgentAutomation,
    Limits,
    Refusal,
    Trigger,
    TriggerKind,
)
from acme.om.agent_projects.types.agent_project import AgentProject, Repository
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.exceptions import ValidationFailed
from acme.om.intake.impl.manager import ROUTED
from acme.om.intake.rules import described
from acme.om.intake.types.event import (
    MAX_TEXT,
    Arrival,
    Author,
    AuthorKind,
    CheckState,
    FeedbackEvent,
    WorkNames,
)
from acme.workers.maintenance.container import WorkerContainer


def feedback_body(org_id: str, event: FeedbackEvent) -> bytes:
    """The message an integration's ingress queues for a verified event."""
    delivery = {"org_id": org_id, "event": event.model_dump(mode="json")}
    return json.dumps(
        {"idempotency_key": str(event.id), "provider": "feedback", "delivery": delivery}
    ).encode()


async def an_agent_project(container: WorkerContainer, ctx: TenantContext) -> UUID:
    """An agent project of the tenant, which an agent automation's session starts in."""
    now = utcnow()
    agent_project = AgentProject(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        name="the checkout service",
        repository=Repository(host="github.com", path="ajax/checkout"),
    )
    return (await container.managers.agent_projects.create_agent_project(ctx, agent_project)).id


def triage(ctx: TenantContext, agent_project_id: UUID | None, limits: Limits) -> AgentAutomation:
    """An agent automation that starts a triage session on a failing check."""
    now = utcnow()
    return AgentAutomation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        name="triage failing checks",
        trigger=Trigger(kind=TriggerKind.EVENT, arrivals=("check",)),
        action=Action(
            kind=ActionKind.START_SESSION,
            brief="Find why.",
            agent_kind="triage",
            title="CI",
            agent_project_id=agent_project_id,
        ),
        limits=limits,
    )


async def test_outside_a_local_stack_an_agent_automation_starts_in_an_agent_project(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    limits = Limits(cost_cap_micros=10, run_cap_micros=1, rate=5, concurrency=1)
    with pytest.raises(ValidationFailed):
        await container.platform.agent_automations.create_agent_automation(
            ctx, triage(ctx, None, limits)
        )


async def test_an_event_from_outside_is_routed_and_fires_agent_automations_once(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    now = utcnow()
    limits = Limits(cost_cap_micros=10, run_cap_micros=1, rate=5, concurrency=1)
    agent_automation = triage(ctx, await an_agent_project(container, ctx), limits)
    await container.platform.agent_automations.create_agent_automation(ctx, agent_automation)
    event = FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=Arrival.CHECK,
        author=Author(kind=AuthorKind.BOT, external_id="ci", name="ci"),
        names=WorkNames(branch="main"),
        check=CheckState.FAILED,
        occurred_at=now,
    )
    consumer = consumer_of(container)
    for _ in range(2):
        assert await consumer.handle(await queued(container, feedback_body(str(ctx.org_id), event)))
    events = await container.managers.events.get_events(ctx, after_seq=0, limit=100)
    (routed,) = [e for e in events if e.kind == ROUTED]
    assert routed.payload["effect"] == "unrouted"
    # The agent automation fired once on the event, and its run is recorded,
    # here refused, since this worker runs no agent kind.
    (run,) = await container.platform.agent_automations.get_runs(ctx, agent_automation.id, 10)
    assert (run.event_id, run.refusal) == (event.id, Refusal.ACTION)
    assert await depth(container) == (0, 0)


async def test_an_event_at_the_text_cap_is_routed_and_fires_once(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    now = utcnow()
    limits = Limits(cost_cap_micros=10, run_cap_micros=1, rate=5, concurrency=1, queue=True)
    agent_automation = triage(ctx, await an_agent_project(container, ctx), limits)
    await container.platform.agent_automations.create_agent_automation(ctx, agent_automation)
    event = FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=Arrival.CHECK,
        author=Author(kind=AuthorKind.BOT, external_id="ci", name="ci"),
        names=WorkNames(branch="main"),
        check=CheckState.FAILED,
        text="x" * MAX_TEXT,
        occurred_at=now,
    )
    assert len(described(event)) <= MAX_TEXT
    consumer = consumer_of(container)
    body = feedback_body(str(ctx.org_id), event)
    assert await consumer.handle(await queued(container, body)) == "applied"
    (run,) = await container.platform.agent_automations.get_runs(ctx, agent_automation.id, 10)
    assert run.event_id == event.id
    assert await depth(container) == (0, 0)
