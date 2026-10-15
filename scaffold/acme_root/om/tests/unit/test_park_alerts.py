"""Park alerts, as the platform runs them: a park that needs a person
tells exactly the people who can clear it, on the platform's own list and
on every account of theirs an integration holds, with the link to the one
action that clears it, and only to a route the API's document holds. One
test per park: a call held for approval, a budget a person must raise, a
call far above its session's norm, a question the agent asks its person,
and any other park on a person."""

import json
import re
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.model_providers import ModelProvidersInterface
from acme.integrations.model_providers.scripted import ScriptedFailure
from acme.integrations.model_providers.types import ErrorKind, ProviderName
from acme.om.agent_billing.rules import ANOMALY_UNLOCK, FUNDS_UNLOCK, price_park
from acme.om.agent_sessions.impl.manager import AgentSessionsOptions
from acme.om.agent_sessions.rules import QUESTION
from acme.om.agent_steps.rules import message_step
from acme.om.agent_steps.types.agent_step import AgentStepType
from acme.om.agent_steps.types.header import Park, ParkReason
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import LoopRun, RunEnd
from acme.om.base import new_id, utcnow
from acme.om.context import Role, TenantContext
from acme.om.evidence.types.provenance import Provenance
from acme.om.language_models.credentials import CallClient, CallCredentialsInterface
from acme.om.park_alerts.types.park_alert import PORTAL, ParkAlert
from acme.om.platform_root import build_platform_managers
from acme.om.spend_budgets.rules import OWN_AMOUNT_UNLOCK
from acme.om.spend_budgets.types.spend_budget import SpendBudget, SpendBudgetScopeKind, WindowKind
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tools.types.policy import Decision, ToolPolicyRule

from contracts.doubles import context
from contracts.factories import make_org
from contracts.intake import STEADY, Wired, wired
from contracts.loops import Lookup, call, reply, said, use
from contracts.park_alert_storage import make_park_alert
from contracts.tools import Command


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
    platform: Wired, ctx: TenantContext, agent_session_id: UUID, text: str = "What is the total?"
) -> LoopRun:
    message = message_step(new_id(), utcnow(), agent_session_id, ctx, text)
    await platform.managers.agent_sessions.receive(ctx, agent_session_id, [message])
    return await platform.loops.run(ctx, agent_session_id)


def told(park_alerts: tuple[ParkAlert, ...]) -> set[tuple[UUID, str]]:
    return {(n.recipient, n.channel) for n in park_alerts}


DOCUMENT = Path(__file__).resolve().parents[3] / "clients" / "typescript" / "openapi.json"
"""The API's committed document: every route it serves."""


def routed(park_alerts: Iterable[ParkAlert]) -> bool:
    """Every link the park alerts carry is a route the API serves, each
    path parameter filled."""
    paths = json.loads(DOCUMENT.read_text())["paths"]
    routes = [re.compile(re.sub(r"\{[^/}]+\}", "[^/]+", path)) for path in paths]
    return all(any(route.fullmatch(n.link) for route in routes) for n in park_alerts if n.link)


async def parked_on(platform: Wired, requester: TenantContext, park: Park) -> LoopRun:
    """A session of `requester`'s that a run parked on `park`."""
    agent_session_id = await platform.start(requester)
    platform.anthropic.add(reply(said("On it.")))
    ended = await run_after(platform, requester, agent_session_id)
    await platform.managers.agent_sessions.park(
        platform.service, agent_session_id, ended.epoch, new_id(), park
    )
    return LoopRun(
        agent_session_id=agent_session_id, epoch=ended.epoch, end=RunEnd.PARKED, park=park
    )


async def test_a_call_held_for_approval_tells_its_eligible_approvers(platform: Wired) -> None:
    found = await people(platform)
    policy = await platform.managers.tools.get_policy(platform.owner)
    rules = (ToolPolicyRule(tool="lookup", decision=Decision.APPROVE),)
    await platform.managers.tools.write_policy(
        platform.owner, policy.model_copy(update={"rules": rules})
    )
    requester = found[Role.MEMBER]
    agent_session_id = await platform.start(requester)
    platform.anthropic.add(reply(use("lookup")))
    run = await run_after(platform, requester, agent_session_id)
    assert run.end is RunEnd.PARKED and run.park is not None
    notified = await platform.park_alerts.notify_park(platform.service, run)
    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    (request,) = [
        s for s in await platform.history(agent_session_id) if s.type is AgentStepType.TOOL_REQUEST
    ]
    link = f"/v1/agent-sessions/{agent_session_id}/calls/{request.seq}/decision"
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
    assert set(await platform.park_alerts.notify_park(platform.service, run)) == set(notified)
    assert len(platform.chat.posted) == 1
    mine = await platform.park_alerts.get_park_alerts(found[Role.ADMIN], 10)
    assert {n.channel for n in mine} == {PORTAL, "chat"}
    assert await platform.park_alerts.get_park_alerts(requester, 10) == ()


async def test_a_budget_park_tells_who_sets_budgets(platform: Wired) -> None:
    found = await people(platform)
    requester = found[Role.MEMBER]
    agent_session_id = await platform.start(requester)
    session = await platform.managers.agent_sessions.get_agent_session(
        platform.owner, agent_session_id
    )
    now = utcnow()
    budget = await platform.managers.spend_budgets.create_spend_budget(
        found[Role.OWNER],
        SpendBudget(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=found[Role.OWNER].user_id,
            updated_by=found[Role.OWNER].user_id,
            scope_kind=SpendBudgetScopeKind.TREE,
            scope_key=str(session.root_id),
            window_kind=WindowKind.LIFE,
            cost_micros=1,
        ),
    )
    platform.anthropic.add(reply(said("On it.")))
    run = await run_after(platform, requester, agent_session_id)
    assert run.park == Park(reason=ParkReason.SPEND_BUDGET, unlock=str(budget.id))
    notified = await platform.park_alerts.notify_park(platform.service, run)
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
    started = await platform.managers.agents.start_agent_session(
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
    notified = await platform.park_alerts.notify_park(platform.service, run)
    assert told(notified) == {(requester.user_id, PORTAL)}
    assert {(n.action, n.link) for n in notified} == {
        ("deadline", f"/v1/agent-sessions/{started.id}/controls")
    }
    assert routed(notified)


SAYS_A_QUESTION_WAITS = (
    "the records asks you a question: read it in the session, and answer with a message."
)


async def asked(platform: Wired, requester: TenantContext, question: str) -> LoopRun:
    """A session of `requester`'s whose agent asked them `question`, and
    then answers once it is answered."""
    started = await platform.managers.agents.start_agent_session(
        requester, Start(id=new_id(), kind="asking", title="the records")
    )
    platform.anthropic.add(
        reply(said("Which week?"), call("ask_person", question=question)),
        reply(said("The report for week 12 is fixed.")),
    )
    run = await run_after(platform, requester, started.id, "Fix the weekly report.")
    assert run.end is RunEnd.PARKED and run.park == QUESTION
    return run


async def test_a_question_tells_its_requester_to_answer_with_a_message_once(
    platform: Wired,
) -> None:
    found = await people(platform)
    requester = found[Role.MEMBER]
    await platform.intake.link_account(platform.owner, "chat", "U-MEMBER", requester.user_id)
    question = 'Which week\'s report is "wrong"?\n\nThe last one,' + " or the one before," * 200
    run = await asked(platform, requester, question)

    notified = await platform.park_alerts.notify_park(platform.service, run)

    assert told(notified) == {(requester.user_id, PORTAL), (requester.user_id, "chat")}
    link = f"/v1/agent-sessions/{run.agent_session_id}/messages"
    assert {(n.action, n.link) for n in notified} == {("answer_question", link)}
    assert routed(notified)
    # The post quotes the question, on one line, escaped, and cut short.
    (posted,) = platform.chat.posted
    assert 'asks you: "Which week\'s report is \\"wrong\\"? The last one, or the one' in posted.text
    assert '…" Answer with a message' in posted.text and len(posted.text) < 400
    assert posted.text.endswith(f" {link}")
    # The rows keep none of it: the question is the session's sealed
    # content, and a row outlives the session's key.
    (text,) = {n.text for n in notified}
    assert text == SAYS_A_QUESTION_WAITS
    for kept in await platform.park_alerts.get_park_alerts(requester, 10):
        assert "week" not in kept.text.lower()
    # The answer is a message, and clears the park: nothing is told again.
    resumed = await run_after(platform, requester, run.agent_session_id, "Week 12.")
    assert resumed.end is RunEnd.ENDED
    assert await platform.park_alerts.notify_park(platform.service, resumed) == ()
    mine = await platform.park_alerts.get_park_alerts(requester, 10)
    assert set(mine) == set(notified) and len(platform.chat.posted) == 1


async def test_a_question_that_holds_a_link_is_not_quoted(platform: Wired) -> None:
    found = await people(platform)
    run = await asked(
        platform, found[Role.MEMBER], "Is ![the chart](https://example.test/c.png?d=1) right?"
    )

    (notified,) = await platform.park_alerts.notify_park(platform.service, run)

    assert notified.text == SAYS_A_QUESTION_WAITS


async def test_a_purged_session_takes_its_park_alerts_and_leaves_the_others(
    tmp_path: Path,
) -> None:
    storage = StorageMemoryImpl()
    managers = build_platform_managers(
        storage,
        InfraLocalImpl(tmp_path),
        agent_kinds=(STEADY,),
        tool_catalog=(Lookup(), Command("call_api")),
        agent_sessions_options=AgentSessionsOptions(retention=timedelta(0)),
    )
    member = context(Role.MEMBER, make_org())
    gone, kept = [
        (
            await managers.agents.start_agent_session(
                member, Start(id=new_id(), kind=STEADY.name, title="the records")
            )
        ).id
        for _ in range(2)
    ]
    park_alerts = storage.get_park_alert_storage()
    for agent_session_id in (gone, gone, kept):
        row = make_park_alert(member.user_id).model_copy(
            update={"agent_session_id": agent_session_id}
        )
        await park_alerts.create_park_alert(member.org_id, row)
    await managers.agent_sessions.delete_agent_session(member, gone)

    assert await managers.agent_sessions.purge_across_tenants() == 1

    left = await park_alerts.read_park_alerts(member.org_id, member.user_id, 10)
    assert {n.agent_session_id for n in left} == {kept} and len(left) == 1


async def test_a_call_far_above_its_norm_tells_who_approves_it_never_its_requester(
    platform: Wired,
) -> None:
    found = await people(platform)
    run = await parked_on(
        platform, found[Role.MEMBER], Park(reason=ParkReason.PERSON, unlock=ANOMALY_UNLOCK)
    )
    notified = await platform.park_alerts.notify_park(platform.service, run)
    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    approval = f"/v1/agent-sessions/{run.agent_session_id}/cost-approval"
    assert {(n.action, n.link) for n in notified} == {("approve_call", approval)}
    (posted,) = platform.chat.posted
    assert posted.text == f"{next(n.text for n in notified if n.channel == 'chat')} {approval}"


async def test_every_link_a_park_alert_carries_is_a_route_of_the_api(
    platform: Wired,
) -> None:
    """A park whose action the API serves links to that route; topping
    up, which the payment provider takes, carries no link at all."""
    found = await people(platform)
    requester = found[Role.MEMBER]
    unlocks = {
        ParkReason.PERSON: ("deadline", ANOMALY_UNLOCK),
        ParkReason.SPEND_BUDGET: (OWN_AMOUNT_UNLOCK, FUNDS_UNLOCK, str(new_id())),
        ParkReason.PROVIDER: ("anthropic:key",),
    }
    notified: list[ParkAlert] = []
    for reason, each in unlocks.items():
        for unlock in each:
            run = await parked_on(platform, requester, Park(reason=reason, unlock=unlock))
            notified.extend(await platform.park_alerts.notify_park(platform.service, run))
    assert {n.action for n in notified} == {
        "deadline",
        "approve_call",
        OWN_AMOUNT_UNLOCK,
        "top_up",
        "raise_budget",
        "save_key",
    }
    assert routed(notified)
    assert {n.action for n in notified if not n.link} == {"top_up"}


async def test_a_key_the_org_lacks_tells_who_saves_its_keys_why_it_waits(
    platform: Wired,
) -> None:
    """A session that needs a key the org holds none of waits for one, with
    no clock: the members who save the org's keys are told, its requester
    not among them, with the route that saves the key and the cause that
    says who acts."""
    found = await people(platform)
    cause = "the org holds no anthropic key: an admin of the org saves one"
    park = Park(reason=ParkReason.PROVIDER, unlock="anthropic:key", cause=cause)
    run = await parked_on(platform, found[Role.MEMBER], park)

    notified = await platform.park_alerts.notify_park(platform.service, run)

    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(notified) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    assert {(n.action, n.link) for n in notified} == {("save_key", "/v1/provider-keys/anthropic")}
    assert all(n.text.endswith(f"waits: {cause}.") for n in notified)
    assert routed(notified)


class OrgKey(CallCredentialsInterface):
    """Every call of the loop goes out on a key the org saved, never the
    platform's."""

    def __init__(self, providers: ModelProvidersInterface) -> None:
        self._providers = providers

    async def client_for(self, ctx: TenantContext, provider: ProviderName) -> CallClient:
        return CallClient(credential="org-key", client=self._providers.get(provider))

    async def refused(self, ctx: TenantContext, provider: ProviderName, credential: str) -> None:
        return None


async def test_a_fix_the_org_makes_at_its_provider_is_told_once_across_its_tries(
    tmp_path: Path,
) -> None:
    """The provider refuses the org's own key for its account's billing:
    the session parks, and tries again every few minutes by itself. The
    members who manage the org are told once, at the first try, with the
    cause that says who acts, and no try after it tells anyone again. Once
    a call goes through, the next such park is a new one, and is told."""
    platform = wired(tmp_path, credentials=OrgKey)
    found = await people(platform)
    requester = found[Role.MEMBER]
    agent_session_id = await platform.start(requester)
    billing = ScriptedFailure(kind=ErrorKind.BILLING, status=402, message="credit balance is low")
    platform.anthropic.add(billing, billing)
    first = await run_after(platform, requester, agent_session_id)
    cause = "anthropic refused the call for its account's billing: an admin of the org settles it"
    assert first.park is not None and first.park.retry_at is not None
    assert (first.park.unlock, first.park.cause) == ("anthropic:billing", cause)

    told_first = await platform.park_alerts.notify_park(platform.service, first)
    await platform.managers.agent_sessions.wake_agent_session(
        platform.service, agent_session_id, first.park
    )
    tried = await platform.loops.run(requester, agent_session_id)
    told_again = await platform.park_alerts.notify_park(platform.service, tried)

    owner, admin = found[Role.OWNER].user_id, found[Role.ADMIN].user_id
    assert told(told_first) == {(owner, PORTAL), (admin, PORTAL), (admin, "chat")}
    assert {(n.action, n.link) for n in told_first} == {("fix_at_provider", "")}
    assert all(n.text.endswith(f"waits: {cause}. It tries again by itself.") for n in told_first)
    assert tried.park is not None and tried.park.unlock == "anthropic:billing", tried
    assert {n.id for n in told_again} == {n.id for n in told_first}, "a try tells nobody again"
    assert len(platform.chat.posted) == 1

    await platform.managers.agent_sessions.wake_agent_session(
        platform.service, agent_session_id, tried.park
    )
    platform.anthropic.add(reply(said("Settled.")), billing)
    assert (await platform.loops.run(requester, agent_session_id)).end is RunEnd.ENDED
    later = await run_after(platform, requester, agent_session_id, "And the next one?")
    told_later = await platform.park_alerts.notify_park(platform.service, later)

    assert told(told_later) == told(told_first)
    assert not {n.id for n in told_later} & {n.id for n in told_first}, "a new park is told"
    assert len(platform.chat.posted) == 2


async def test_a_park_that_clears_by_itself_tells_nobody(platform: Wired) -> None:
    await people(platform)
    agent_session_id = await platform.start()
    platform.anthropic.add(reply(said("Done.")))
    ended = await run_after(platform, platform.owner, agent_session_id)
    assert await platform.park_alerts.notify_park(platform.service, ended) == ()
    retries = (
        Park(reason=ParkReason.SPEND_BUDGET, unlock="held", retry_at=utcnow()),
        # A price, and a key the platform's operator fixes, wait for no one
        # of the tenant's, and try again by themselves.
        price_park(utcnow()),
        Park(reason=ParkReason.PROVIDER, unlock="anthropic:credential", retry_at=utcnow()),
    )
    for retry in retries:
        parked = LoopRun(agent_session_id=agent_session_id, epoch=1, end=RunEnd.PARKED, park=retry)
        assert await platform.park_alerts.notify_park(platform.service, parked) == ()
