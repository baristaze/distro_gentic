"""Notifications, as the platform runs them: a park that needs a person
tells exactly the people who can clear it, on the platform's own list and
on every account of theirs an integration holds, with the link to the one
action that clears it, and only to a route the API's document holds. One
test per park: a call held for approval, a budget a person must raise, a
call far above its session's norm, and any other park on a person."""

import json
import re
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.intake import Wired, wired
from contracts.loops import reply, said, use

from acme.om.agents.types.request import Start
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.base import new_id, utcnow
from acme.om.billing.rules import ANOMALY_UNLOCK, FUNDS_UNLOCK
from acme.om.budgets.rules import OWN_AMOUNT_UNLOCK
from acme.om.budgets.types.budget import Budget, BudgetScopeKind, WindowKind
from acme.om.context import Role, TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.notifications.types.notification import PORTAL, Notification
from acme.om.steps.rules import message_step
from acme.om.steps.types.header import Park, ParkReason
from acme.om.steps.types.step import StepType
from acme.om.tools.types.policy import Decision, PolicyRule


@pytest.fixture
def platform(tmp_path: Path) -> Wired:
    return wired(tmp_path)


async def people(platform: Wired) -> dict[Role, TenantContext]:
    """An owner, an admin whose chat account is linked, a member, and a
    viewer, each a member of the tenant."""
    found = {role: await platform.member(role) for role in (Role.OWNER, Role.ADMIN, Role.MEMBER)}
    found[Role.VIEWER] = await platform.member(Role.VIEWER)
    await platform.intake.link_account(platform.owner, "chat", "U-ADMIN", found[Role.ADMIN].user_id)
    return found


async def run_after(
    platform: Wired, ctx: TenantContext, session_id: UUID, text: str = "What is the total?"
) -> LoopRun:
    message = message_step(new_id(), utcnow(), session_id, ctx, text)
    await platform.managers.agent_sessions.receive(ctx, session_id, [message])
    return await platform.loops.run(ctx, session_id)


def told(notifications: tuple[Notification, ...]) -> set[tuple[UUID, str]]:
    return {(n.recipient, n.channel) for n in notifications}


DOCUMENT = Path(__file__).resolve().parents[3] / "clients" / "typescript" / "openapi.json"
"""The API's committed document: every route it serves."""


def routed(notifications: Iterable[Notification]) -> bool:
    """Every link the notifications carry is a route the API serves, each
    path parameter filled."""
    paths = json.loads(DOCUMENT.read_text())["paths"]
    routes = [re.compile(re.sub(r"\{[^/}]+\}", "[^/]+", path)) for path in paths]
    return all(any(route.fullmatch(n.link) for route in routes) for n in notifications if n.link)


async def parked_on(platform: Wired, requester: TenantContext, park: Park) -> LoopRun:
    """A session of `requester`'s that a run parked on `park`."""
    session_id = await platform.start(requester)
    platform.anthropic.add(reply(said("On it.")))
    ended = await run_after(platform, requester, session_id)
    await platform.managers.agent_sessions.park(
        platform.service, session_id, ended.epoch, new_id(), park
    )
    return LoopRun(session_id=session_id, epoch=ended.epoch, end=RunEnd.PARKED, park=park)


async def test_a_call_held_for_approval_tells_its_eligible_approvers(platform: Wired) -> None:
    found = await people(platform)
    policy = await platform.managers.tools.get_policy(platform.owner)
    rules = (PolicyRule(tool="lookup", decision=Decision.APPROVE),)
    await platform.managers.tools.write_policy(
        platform.owner, policy.model_copy(update={"rules": rules})
    )
    requester = found[Role.MEMBER]
    session_id = await platform.start(requester)
    platform.anthropic.add(reply(use("lookup")))
    run = await run_after(platform, requester, session_id)
    assert run.end is RunEnd.PARKED and run.park is not None
    notified = await platform.notifications.notify_park(platform.service, run)
    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    (request,) = [s for s in await platform.history(session_id) if s.type is StepType.TOOL_REQUEST]
    link = f"/v1/agent-sessions/{session_id}/calls/{request.seq}/decision"
    assert {(n.action, n.link) for n in notified} == {("decide_call", link)}
    assert routed(notified)
    # The chat post is the twin's, and says so on the record and the post.
    (posted,) = platform.chat.posted
    (by_chat,) = [n for n in notified if n.channel == "chat"]
    assert (posted.address, by_chat.address, by_chat.provenance) == (
        "U-ADMIN",
        "U-ADMIN",
        Provenance.TWIN,
    )
    assert link in posted.text and posted.provenance == "twin"
    # Told once a park, however often it is asked.
    assert set(await platform.notifications.notify_park(platform.service, run)) == set(notified)
    assert len(platform.chat.posted) == 1
    mine = await platform.notifications.get_notifications(found[Role.ADMIN], 10)
    assert {n.channel for n in mine} == {PORTAL, "chat"}
    assert await platform.notifications.get_notifications(requester, 10) == ()


async def test_a_budget_park_tells_who_sets_budgets(platform: Wired) -> None:
    found = await people(platform)
    requester = found[Role.MEMBER]
    session_id = await platform.start(requester)
    session = await platform.managers.agent_sessions.get_session(platform.owner, session_id)
    now = utcnow()
    budget = await platform.managers.budgets.create_budget(
        found[Role.OWNER],
        Budget(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=found[Role.OWNER].user_id,
            updated_by=found[Role.OWNER].user_id,
            scope_kind=BudgetScopeKind.TREE,
            scope_key=str(session.root_id),
            window_kind=WindowKind.LIFE,
            cost_micros=1,
        ),
    )
    platform.anthropic.add(reply(said("On it.")))
    run = await run_after(platform, requester, session_id)
    assert run.park == Park(reason=ParkReason.BUDGET, unlock=str(budget.id))
    notified = await platform.notifications.notify_park(platform.service, run)
    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    # The link is the budget's amount, and the text names the budget.
    link = f"/v1/budgets/{budget.id}/amount"
    assert {(n.action, n.link) for n in notified} == {("raise_budget", link)}
    assert all(str(budget.id) in n.text for n in notified)
    assert routed(notified)


async def test_a_park_on_a_person_tells_its_requester_alone(platform: Wired) -> None:
    found = await people(platform)
    requester = found[Role.MEMBER]
    started = await platform.managers.agents.start_session(
        requester,
        Start(
            id=new_id(),
            kind="steady",
            title="the records",
            deadline=platform.clock.now + timedelta(minutes=1),
        ),
    )
    platform.clock.now += timedelta(minutes=2)
    run = await run_after(platform, requester, started.id)
    assert run.end is RunEnd.PARKED and run.park is not None
    assert (run.park.reason, run.park.unlock) == (ParkReason.PERSON, "deadline")
    notified = await platform.notifications.notify_park(platform.service, run)
    assert told(notified) == {(requester.user_id, PORTAL)}
    assert {(n.action, n.link) for n in notified} == {
        ("deadline", f"/v1/agent-sessions/{started.id}/controls")
    }
    assert routed(notified)


async def test_a_call_far_above_its_norm_tells_who_approves_it_never_its_requester(
    platform: Wired,
) -> None:
    found = await people(platform)
    run = await parked_on(
        platform, found[Role.MEMBER], Park(reason=ParkReason.PERSON, unlock=ANOMALY_UNLOCK)
    )
    notified = await platform.notifications.notify_park(platform.service, run)
    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    assert {(n.action, n.link) for n in notified} == {("approve_call", "")}
    (posted,) = platform.chat.posted
    assert posted.text == next(n.text for n in notified if n.channel == "chat")


async def test_every_link_a_notification_carries_is_a_route_of_the_api(
    platform: Wired,
) -> None:
    """A park whose action the API serves links to that route; one whose
    action has no route yet carries no link at all."""
    found = await people(platform)
    requester = found[Role.MEMBER]
    unlocks = {
        ParkReason.PERSON: ("deadline", ANOMALY_UNLOCK),
        ParkReason.BUDGET: (OWN_AMOUNT_UNLOCK, FUNDS_UNLOCK, str(new_id())),
    }
    notified: list[Notification] = []
    for reason, each in unlocks.items():
        for unlock in each:
            run = await parked_on(platform, requester, Park(reason=reason, unlock=unlock))
            notified.extend(await platform.notifications.notify_park(platform.service, run))
    assert {n.action for n in notified} == {
        "deadline",
        "approve_call",
        OWN_AMOUNT_UNLOCK,
        "top_up",
        "raise_budget",
    }
    assert routed(notified)
    assert {n.action for n in notified if not n.link} == {"approve_call", "top_up"}


async def test_a_park_that_clears_by_itself_tells_nobody(platform: Wired) -> None:
    await people(platform)
    session_id = await platform.start()
    platform.anthropic.add(reply(said("Done.")))
    ended = await run_after(platform, platform.owner, session_id)
    assert await platform.notifications.notify_park(platform.service, ended) == ()
    retry = Park(reason=ParkReason.BUDGET, unlock="held", retry_at=utcnow())
    parked = LoopRun(session_id=session_id, epoch=1, end=RunEnd.PARKED, park=retry)
    assert await platform.notifications.notify_park(platform.service, parked) == ()
