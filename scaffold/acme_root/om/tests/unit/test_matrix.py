"""Models are a fleet decision: the matrix answers every question with its
most specific row, a fill enters only priced and qualified, a tenant's
retention filters what it resolves to, a session keeps its version across a
publication and switches off a retired model at its next loop, and a tenant
on its own keys calls on them, alone."""

import itertools
from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.factories import make_org
from contracts.loops import reply, said
from contracts.matrix import (
    CATCH_ALL,
    EU,
    HAIKU,
    LUNA,
    OPUS,
    SOL,
    SONNET,
    UNPRICED,
    Fleet,
    fleet_over,
    kept_in,
)

from acme.integrations.model_providers.calls import ModelCall
from acme.integrations.model_providers.scripted import ScriptedFailure
from acme.integrations.model_providers.types import ErrorKind, ProviderName
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.billing.types.account import AccountRequest, FundingMode
from acme.om.billing.types.ledger import EntryKind, FundedHold
from acme.om.context import Role, TenantContext
from acme.om.exceptions import (
    NotFound,
    PreconditionFailed,
    SpenderUnknown,
    ValidationFailed,
)
from acme.om.matrix import rules
from acme.om.matrix.types.matrix import (
    KEYS,
    MatrixKey,
    MatrixQuery,
    MatrixRow,
    MatrixStatus,
)
from acme.om.matrix.types.record import ModelRef
from acme.om.models.types.fill import MAIN, SUMMARIZER, Eligibility, Fill, SwitchReason
from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention import rules as retention_rules
from acme.om.retention.types.policy import RetentionPolicy
from acme.om.steps.types.header import LoopOutcome, ParkReason, SwitchedHeader
from acme.om.steps.types.step import StepType
from acme.om.trust.types.provider_key import KeyStatus


def anywhere(_: Fill) -> bool:
    return True


def a_start() -> Start:
    return Start(id=new_id(), kind="assistant", title="a question")


async def loop_once(fleet: Fleet, session_id: UUID, text: str = "What is the total?") -> RunEnd:
    await fleet.loop.say(session_id, text)
    ran = await fleet.loop.loops.run(fleet.owner, session_id)
    return ran.end


async def switches(fleet: Fleet, session_id: UUID) -> list[SwitchedHeader]:
    return [
        step.header
        for step in await fleet.loop.history(session_id)
        if isinstance(step.header, SwitchedHeader)
    ]


# A matrix without the row that matches everything is refused, and every
# question resolves.


async def test_a_matrix_without_the_row_that_matches_everything_is_refused_at_publish(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    operators = fleet.matrix.matrix_operator
    rows = CATCH_ALL[:2]
    version = await operators.stage(fleet.admin, (MAIN, SUMMARIZER), rows)
    for row in version.rows:
        for fill in row.fills:
            await fleet.qualify(fill, *version.roles_of(row))

    with pytest.raises(ValidationFailed, match="no row matches every question"):
        await operators.publish(fleet.admin, version.number)

    assert (await operators.get_version(fleet.admin, version.number)).status is (
        MatrixStatus.PENDING
    )
    with pytest.raises(NotFound):
        await operators.get_version(fleet.admin, None)
    session_id = await fleet.loop.start()
    assert await loop_once(fleet, session_id) is RunEnd.ENDED, "no published matrix, no model"
    assert fleet.loop.anthropic.calls == [] and fleet.loop.openai.calls == []


def test_every_question_resolves_to_its_most_specific_matching_row() -> None:
    """Over every question the rows' values and an unnamed value make, each
    resolves, to the row that names the most keys among those that match,
    the spec's order breaking a tie."""
    rows = (
        MatrixRow(fills=(SONNET,)),
        MatrixRow(key=MatrixKey(role=MAIN), fills=(OPUS,)),
        MatrixRow(key=MatrixKey(environment="production"), fills=(SOL,)),
        MatrixRow(key=MatrixKey(kind="engineer", plan_tier="pro"), fills=(LUNA,)),
        MatrixRow(key=MatrixKey(role=MAIN, workload="batch"), fills=(HAIKU,)),
        MatrixRow(
            key=MatrixKey(environment="production", role=MAIN, kind="engineer"),
            fills=(kept_in(SONNET, EU),),
        ),
    )
    values = {
        "environment": ("production", "staging"),
        "role": (MAIN, SUMMARIZER),
        "kind": ("engineer", "assistant"),
        "plan_tier": ("pro", "standard"),
        "workload": ("batch", "standard"),
    }
    for combination in itertools.product(*(values[key] for key in KEYS)):
        query = MatrixQuery(**dict(zip(KEYS, combination, strict=True)))
        matching = [row for row in rows if row.key.matches(query)]
        expected = max(matching, key=lambda row: row.key.specificity)
        assert rules.answer(rows, query, anywhere) == expected.fills, query

    query = MatrixQuery(
        environment="production", role=MAIN, kind="engineer", plan_tier="pro", workload="batch"
    )
    assert rules.answer(rows, query, anywhere) == (kept_in(SONNET, EU),), "three keys beat two"
    tie = query.model_copy(update={"kind": "assistant", "workload": "standard"})
    assert rules.answer(rows, tie, anywhere) == (SOL,), "the environment comes first in a tie"


# A model enters a role's fills only priced, and only qualified for it.


async def test_a_model_without_a_price_row_of_its_own_enters_no_version(tmp_path: Path) -> None:
    fleet = await fleet_over(tmp_path)
    rows = (MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET, UNPRICED)), *CATCH_ALL[1:])

    with pytest.raises(ValidationFailed, match="a-model-the-list-does-not-hold has no price row"):
        await fleet.publish(rows)

    with pytest.raises(NotFound):
        await fleet.matrix.matrix_operator.get_version(fleet.admin, None)


async def test_a_model_enters_only_the_roles_a_passing_benchmark_qualified_it_for(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    operators = fleet.matrix.matrix_operator
    version = await operators.stage(fleet.admin, (MAIN, SUMMARIZER), CATCH_ALL)
    await fleet.qualify(SONNET, MAIN)  # the row that matches everything serves both
    await fleet.qualify(SOL, MAIN)
    await fleet.qualify(HAIKU, SUMMARIZER)
    await fleet.qualify(LUNA, SUMMARIZER, passed=False)

    with pytest.raises(ValidationFailed) as refused:
        await operators.publish(fleet.admin, version.number)

    said_ = refused.value.message
    assert "openai/gpt-6-luna has no passing benchmark for the model role summarizer" in said_
    assert "anthropic/claude-sonnet-5-5 has no passing benchmark for the model role summarizer" in (
        said_
    )
    assert "gpt-6.1-sol" not in said_, "qualified for the one role its row serves"
    await fleet.qualify(SONNET, SUMMARIZER)
    await fleet.qualify(LUNA, SUMMARIZER)
    published = await operators.publish(fleet.admin, version.number)
    assert published.status is MatrixStatus.PUBLISHED
    with pytest.raises(PreconditionFailed):
        await operators.publish(fleet.admin, version.number)

    later = await operators.stage(fleet.admin, (MAIN, SUMMARIZER), CATCH_ALL)
    await fleet.qualify(SOL, MAIN, passed=False)
    with pytest.raises(ValidationFailed, match=r"gpt-6\.1-sol has no passing benchmark"):
        await operators.publish(fleet.admin, later.number)


# A tenant's retention filters resolution, fallbacks included.


async def test_a_tenant_that_keeps_nothing_in_one_region_resolves_only_to_fills_that_meet_it(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    sol_eu, sonnet_eu, haiku_eu = kept_in(SOL, EU), kept_in(SONNET, EU), kept_in(HAIKU, EU)
    elsewhere = kept_in(OPUS, Eligibility(zero_retention=True, region="us-east-1"))
    await fleet.publish(
        (
            # The most specific row for the kind offers nothing the tenant
            # may run on, so a less specific one answers.
            MatrixRow(key=MatrixKey(role=MAIN, kind="assistant"), fills=(OPUS, elsewhere)),
            MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET, sol_eu, elsewhere, sonnet_eu)),
            MatrixRow(key=MatrixKey(role=SUMMARIZER), fills=(HAIKU, haiku_eu)),
            MatrixRow(fills=(SONNET,)),
        )
    )
    current = await fleet.loop.managers.retention.get_policy(fleet.owner)
    kept = RetentionPolicy(
        storage_mode=StorageMode.MEMORY_ONLY, zero_retention=True, region="eu-central-1"
    )
    await fleet.loop.managers.retention.write_policy(
        fleet.owner, current.model_copy(update={"policy": kept})
    )
    session_id = await fleet.loop.start()
    overloaded = ScriptedFailure(kind=ErrorKind.OVERLOADED, retry_after=2)
    fleet.loop.openai.add(overloaded, overloaded, overloaded)
    fleet.loop.anthropic.add(overloaded, overloaded, overloaded)

    parked = await loop_once(fleet, session_id)

    assert parked is RunEnd.PARKED, "its last eligible fallback failed too"
    (fell,) = await switches(fleet, session_id)
    assert (fell.fills.from_fill, fell.fills.to_fill) == (sol_eu, sonnet_eu)
    fills = await fleet.loop.managers.models.get_fill_set(fleet.owner, session_id)
    assert fills.eligibility == EU, "the fill set holds what the tenant requires"
    assert (fills.roles[0].fill, fills.roles[0].fallbacks) == (sonnet_eu, ())
    assert (fills.roles[1].fill, fills.roles[1].fallbacks) == (haiku_eu, ())
    models = {call.model for call in (*fleet.loop.openai.calls, *fleet.loop.anthropic.calls)}
    assert models == {SOL.model, SONNET.model}, "no call reached a fill it forbade"

    other = context(Role.OWNER, make_org())
    await fleet.money.billing.open_account(
        other, AccountRequest(funding=FundingMode.PLATFORM, plan_id="starter", zone="UTC")
    )
    unkept = await fleet.loop.managers.agents.start_session(other, a_start())
    await fleet.loop.managers.models.resolve_fill_set(
        other, unkept.id, (MAIN, SUMMARIZER), Eligibility()
    )
    theirs = await fleet.loop.managers.models.get_fill_set(other, unkept.id)
    assert theirs.roles[0].fill == OPUS, "a tenant that requires nothing takes the kind's row"


async def test_a_tightened_retention_reaches_a_running_sessions_fills_at_its_next_loop(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    sonnet_eu, haiku_eu = kept_in(SONNET, EU), kept_in(HAIKU, EU)
    await fleet.publish(
        (
            MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET, SOL, sonnet_eu)),
            MatrixRow(key=MatrixKey(role=SUMMARIZER), fills=(HAIKU, haiku_eu)),
            MatrixRow(fills=(SONNET,)),
        )
    )
    session_id = await fleet.loop.start()
    fleet.loop.anthropic.add(reply(said("The total is 12.")))
    assert await loop_once(fleet, session_id) is RunEnd.ENDED

    # The tenant now keeps nothing and stays in one region, and the sweep
    # folds it into the session's snapshot.
    retention = fleet.loop.managers.retention
    current = await retention.get_policy(fleet.owner)
    kept = RetentionPolicy(
        storage_mode=StorageMode.MEMORY_ONLY, zero_retention=True, region="eu-central-1"
    )
    written = await retention.write_policy(fleet.owner, current.model_copy(update={"policy": kept}))
    snapshots = fleet.loop.storage.get_retention_storage()
    snapshot = await snapshots.read_snapshot(fleet.owner.org_id, session_id)
    assert snapshot is not None
    tightened = retention_rules.folded(snapshot, kept, written.version, fleet.loop.clock())
    assert await snapshots.write_snapshot(fleet.owner.org_id, tightened, snapshot.version)
    overloaded = ScriptedFailure(kind=ErrorKind.OVERLOADED, retry_after=2)
    fleet.loop.anthropic.add(overloaded, overloaded, overloaded)

    assert await loop_once(fleet, session_id, "And the average?") is RunEnd.PARKED

    moved = {
        (s.fills.from_fill, s.fills.to_fill, s.fills.reason)
        for s in await switches(fleet, session_id)
    }
    assert moved == {
        (SONNET, sonnet_eu, SwitchReason.POLICY),
        (HAIKU, haiku_eu, SwitchReason.POLICY),
    }
    assert fleet.loop.openai.calls == [], "the fallback it no longer admits is never taken"


# A running session keeps its version, and a retired model switches at the
# next loop.


async def test_a_running_session_keeps_its_matrix_version_across_a_publish(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    first = await fleet.publish()
    session_id = await fleet.loop.start()
    fleet.loop.anthropic.add(reply(said("The total is 12.")))
    assert await loop_once(fleet, session_id) is RunEnd.ENDED

    second = await fleet.publish(
        (MatrixRow(key=MatrixKey(role=MAIN), fills=(SOL,)), *CATCH_ALL[1:])
    )
    fleet.loop.anthropic.add(reply(said("The average is 3.")))
    assert await loop_once(fleet, session_id, "And the average?") is RunEnd.ENDED

    assert fleet.loop.openai.calls == [], "the session kept the version it started with"
    assert [call.model for call in fleet.loop.anthropic.calls] == [SONNET.model] * 2
    assert await switches(fleet, session_id) == []
    pin = await fleet.matrix.matrix.get_pin(fleet.owner, session_id)
    assert (pin.matrix_version, pin.fill_set_version) == (first.number, 1)
    fresh = await fleet.loop.start()
    fleet.loop.openai.add(reply(said("The total is 12."), model=SOL.model))
    assert await loop_once(fleet, fresh) is RunEnd.ENDED
    assert (await fleet.matrix.matrix.get_pin(fleet.owner, fresh)).matrix_version == (second.number)


async def test_a_retired_model_switches_at_the_next_loop_with_a_switched_step(
    tmp_path: Path,
) -> None:
    fleet = await fleet_over(tmp_path)
    await fleet.publish((MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET,)), *CATCH_ALL[1:]))
    session_id = await fleet.loop.start()
    overloaded = ScriptedFailure(kind=ErrorKind.OVERLOADED, retry_after=2)
    fleet.loop.anthropic.add(overloaded, overloaded, overloaded)
    assert await loop_once(fleet, session_id) is RunEnd.PARKED, "no fallback: it waits"

    # The provider retires the model while the loop waits, and the matrix
    # names another. The loop resumes on the model it began with.
    second = await fleet.publish(
        (MatrixRow(key=MatrixKey(role=MAIN), fills=(OPUS,)), *CATCH_ALL[1:])
    )
    await fleet.matrix.matrix_operator.retire_model(fleet.admin, ModelRef.of(SONNET))
    session = await fleet.loop.managers.agent_sessions.get_session(fleet.owner, session_id)
    assert session.park is not None and session.park.retry_at is not None
    fleet.loop.clock.now = session.park.retry_at
    await fleet.loop.managers.agent_sessions.wake_session(fleet.owner, session_id, session.park)
    fleet.loop.anthropic.add(reply(said("The total is 12.")))
    resumed = await fleet.loop.loops.run(fleet.owner, session_id)
    assert resumed.outcome is LoopOutcome.SUCCEEDED
    assert await switches(fleet, session_id) == [], "never inside a loop"

    fleet.loop.anthropic.add(reply(said("The average is 3."), model=OPUS.model))
    assert await loop_once(fleet, session_id, "And the average?") is RunEnd.ENDED

    (switched,) = await switches(fleet, session_id)
    assert (switched.fills.from_fill, switched.fills.to_fill) == (SONNET, OPUS)
    assert switched.fills.reason is SwitchReason.RETIRED
    at = [step.type for step in await fleet.loop.history(session_id)]
    last_request = max(i for i, kind in enumerate(at) if kind is StepType.MODEL_REQUEST)
    assert at.index(StepType.SWITCHED) < last_request, "switched before the loop's first call"
    assert [call.model for call in fleet.loop.anthropic.calls][-1] == OPUS.model
    pin = await fleet.matrix.matrix.get_pin(fleet.owner, session_id)
    assert (pin.fill_set_version, pin.matrix_version) == (2, second.number)
    fresh = await fleet.loop.start()
    await fleet.loop.managers.models.resolve_fill_set(
        fleet.owner, fresh, (MAIN, SUMMARIZER), Eligibility()
    )
    assert (await fleet.loop.managers.models.get_fill_set(fleet.owner, fresh)).fill_for(
        MAIN
    ) == OPUS


async def test_a_version_naming_a_retired_model_is_never_published(tmp_path: Path) -> None:
    fleet = await fleet_over(tmp_path)
    await fleet.matrix.matrix_operator.retire_model(fleet.admin, ModelRef.of(SOL))
    again = await fleet.matrix.matrix_operator.retire_model(fleet.admin, ModelRef.of(SOL))
    assert again.model == SOL.model
    with pytest.raises(ValidationFailed, match=r"gpt-6\.1-sol is retired"):
        await fleet.publish()


# A tenant on its own keys calls on them, and on nothing else.


async def own_keys(tmp_path: Path, *providers: ProviderName) -> tuple[Fleet, dict[str, UUID]]:
    fleet = await fleet_over(tmp_path, funding=FundingMode.OWN_KEY)
    saved = {}
    for provider in providers:
        value = f"sk-{provider.value}"
        key = await fleet.trust.trust.save_provider_key(fleet.owner, provider, value)
        saved[value] = key.id
    return fleet, saved


async def test_an_own_key_tenants_calls_go_out_on_its_key_reference(tmp_path: Path) -> None:
    fleet, saved = await own_keys(tmp_path, ProviderName.ANTHROPIC)
    await fleet.publish()
    session_id = await fleet.loop.start()
    fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).add(reply(said("The total is 12.")))

    assert await loop_once(fleet, session_id) is RunEnd.ENDED

    fills = await fleet.loop.managers.models.get_fill_set(fleet.owner, session_id)
    assert fills.roles[0].fallbacks == (), "no fallback on a provider it holds no key for"
    assert len(fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).calls) == 1
    assert fleet.loop.anthropic.calls == [] and fleet.loop.openai.calls == [], (
        "never the platform's"
    )
    (hold,) = await fleet.money.ledger.read_entries(
        fleet.owner.org_id, kind=EntryKind.HOLD, limit=10
    )
    assert isinstance(hold, FundedHold)
    assert hold.funding.mode is FundingMode.OWN_KEY
    assert hold.funding.credential == str(saved["sk-anthropic"])


async def test_billing_holds_an_own_key_call_only_when_it_carries_the_tenants_key(
    tmp_path: Path,
) -> None:
    fleet, saved = await own_keys(tmp_path, ProviderName.ANTHROPIC)
    await fleet.publish()
    session_id = await fleet.loop.start()
    call = ModelCall(model=SONNET.model, messages=(), max_output_tokens=4_000)
    payer = Principal(kind=PrincipalKind.PERSON, id=fleet.owner.user_id)
    with pytest.raises(SpenderUnknown, match="does not carry the tenant's own key"):
        await fleet.money.calls.authorize(
            fleet.owner, session_id, payer, MAIN, SONNET, call, credential="platform"
        )
    assert await fleet.money.ledger.read_entries(fleet.owner.org_id, limit=10) == []
    held = await fleet.money.calls.authorize(
        fleet.owner, session_id, payer, MAIN, SONNET, call, credential=str(saved["sk-anthropic"])
    )
    assert (await fleet.money.gate.read_hold(fleet.owner, held)).funding.mode is (
        FundingMode.OWN_KEY
    )

    platform, _ = await platform_tenant(fleet)
    other = await fleet.loop.managers.agents.start_session(platform, a_start())
    with pytest.raises(SpenderUnknown, match="carries a tenant's key"):
        await fleet.money.calls.authorize(
            platform, other.id, payer, MAIN, SONNET, call, credential=str(saved["sk-anthropic"])
        )


async def platform_tenant(fleet: Fleet) -> tuple[TenantContext, UUID]:
    """A second tenant, on the platform's key, with a session of its own."""
    other = context(Role.OWNER, make_org())
    await fleet.money.billing.open_account(
        other, AccountRequest(funding=FundingMode.PLATFORM, plan_id="starter", zone="UTC")
    )
    session = await fleet.loop.managers.agents.start_session(other, a_start())
    return other, session.id


async def test_a_session_needing_a_key_its_tenant_lacks_parks_and_spends_nothing(
    tmp_path: Path,
) -> None:
    fleet, _ = await own_keys(tmp_path)
    await fleet.publish()
    session_id = await fleet.loop.start()

    assert await loop_once(fleet, session_id) is RunEnd.PARKED

    session = await fleet.loop.managers.agent_sessions.get_session(fleet.owner, session_id)
    assert session.park is not None and session.park.reason is ParkReason.PROVIDER
    assert session.park.unlock == "anthropic:key" and session.park.retry_at is None
    assert fleet.loop.anthropic.calls == [] and fleet.loop.openai.calls == []
    assert await fleet.money.ledger.read_entries(fleet.owner.org_id, limit=10) == []


async def test_a_refused_key_parks_only_the_sessions_that_need_it(tmp_path: Path) -> None:
    batch: set[UUID] = set()
    fleet = await fleet_over(
        tmp_path,
        funding=FundingMode.OWN_KEY,
        workload=lambda session: "batch" if session.id in batch else "standard",
    )
    a = await fleet.trust.trust.save_provider_key(fleet.owner, ProviderName.ANTHROPIC, "sk-a")
    await fleet.trust.trust.save_provider_key(fleet.owner, ProviderName.OPENAI, "sk-o")
    await fleet.publish(
        (
            MatrixRow(key=MatrixKey(role=MAIN, workload="batch"), fills=(SOL,)),
            MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET,)),
            *CATCH_ALL[1:],
        )
    )
    first = await fleet.loop.start()
    second = await fleet.loop.start()
    on_openai = await fleet.loop.start()
    batch.add(on_openai)
    fleet.on_key("sk-a", ProviderName.ANTHROPIC).add(
        ScriptedFailure(kind=ErrorKind.CREDENTIAL, status=401)
    )
    fleet.on_key("sk-o", ProviderName.OPENAI).add(reply(said("The total is 12."), model=SOL.model))
    platform, theirs = await platform_tenant(fleet)
    fleet.loop.anthropic.add(reply(said("The total is 12.")))

    assert await loop_once(fleet, first) is RunEnd.PARKED
    assert await loop_once(fleet, second) is RunEnd.PARKED
    assert await loop_once(fleet, on_openai) is RunEnd.ENDED
    await fleet.loop.say(theirs, "What is the total?", platform)
    assert (await fleet.loop.loops.run(platform, theirs)).end is RunEnd.ENDED

    parks = [
        (await fleet.loop.managers.agent_sessions.get_session(fleet.owner, s)).park
        for s in (first, second)
    ]
    assert [p.unlock if p else None for p in parks] == ["anthropic:credential", "anthropic:key"]
    assert len(fleet.on_key("sk-a", ProviderName.ANTHROPIC).calls) == 1, (
        "the second parked before it called"
    )
    keys = {k.id: k for k in await fleet.trust.trust.get_provider_keys(fleet.owner, 10)}
    assert keys[a.id].status is KeyStatus.REFUSED
    assert len(fleet.loop.anthropic.calls) == 1, "the other tenant's call ran on the platform's"


async def test_an_own_key_tenants_outage_signal_is_its_own(tmp_path: Path) -> None:
    fleet, saved = await own_keys(tmp_path, ProviderName.ANTHROPIC)
    await fleet.publish()
    first = await fleet.loop.start()
    overloaded = ScriptedFailure(kind=ErrorKind.OVERLOADED, retry_after=2)
    fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).add(overloaded, overloaded, overloaded)
    platform, theirs = await platform_tenant(fleet)
    fleet.loop.anthropic.add(reply(said("The total is 12.")))

    assert await loop_once(fleet, first) is RunEnd.PARKED
    second = await fleet.loop.start()
    assert await loop_once(fleet, second) is RunEnd.PARKED
    await fleet.loop.say(theirs, "What is the total?", platform)
    assert (await fleet.loop.loops.run(platform, theirs)).end is RunEnd.ENDED

    outages = fleet.loop.infra.get_outages()
    now = fleet.loop.clock()
    key = str(saved["sk-anthropic"])
    assert await outages.current("anthropic", key, now) is not None
    assert await outages.current("anthropic", "platform", now) is None
    assert len(fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).calls) == 3, (
        "the second parked on the signal"
    )
    assert len(fleet.loop.anthropic.calls) == 1


# A tenant chooses only among qualified fills, on its own keys.


async def test_a_tenant_on_its_own_keys_chooses_only_among_qualified_fills_it_holds_keys_for(
    tmp_path: Path,
) -> None:
    fleet, _ = await own_keys(tmp_path, ProviderName.ANTHROPIC)
    choose = fleet.matrix.matrix.choose_fill
    await fleet.publish(
        (
            MatrixRow(key=MatrixKey(role=MAIN, plan_tier="pro"), fills=(OPUS,)),
            *CATCH_ALL,
        )
    )
    with pytest.raises(ValidationFailed, match="no live openai key"):
        await choose(fleet.owner, MAIN, SOL)
    with pytest.raises(ValidationFailed, match="qualified"):
        await choose(fleet.owner, SUMMARIZER, OPUS)
    chosen = await choose(fleet.owner, MAIN, OPUS)
    assert await fleet.matrix.matrix.get_choices(fleet.owner) == (chosen,)

    session_id = await fleet.loop.start()
    fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).add(
        reply(said("The total is 12."), model=OPUS.model)
    )
    assert await loop_once(fleet, session_id) is RunEnd.ENDED
    fills = await fleet.loop.managers.models.get_fill_set(fleet.owner, session_id)
    assert (fills.roles[0].fill, fills.roles[0].fallbacks) == (OPUS, (SONNET,))

    platform, _ = await platform_tenant(fleet)
    with pytest.raises(ValidationFailed, match="own keys"):
        await choose(platform, MAIN, OPUS)
    assert await fleet.matrix.matrix.drop_choice(fleet.owner, MAIN)
    assert await fleet.matrix.matrix.get_choices(fleet.owner) == ()


async def test_a_purged_tenants_pins_and_choices_go_with_its_fill_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fleet, _ = await own_keys(tmp_path, ProviderName.ANTHROPIC)
    await fleet.publish()
    await fleet.matrix.matrix.choose_fill(fleet.owner, MAIN, SONNET)
    session_id = await fleet.loop.start()
    fleet.on_key("sk-anthropic", ProviderName.ANTHROPIC).add(reply(said("The total is 12.")))
    assert await loop_once(fleet, session_id) is RunEnd.ENDED
    models = fleet.loop.managers.models
    assert await models.purge_tenant(fleet.owner) == 0, "a living tenant keeps everything"

    async def expired(ctx: object) -> bool:
        return True

    monkeypatch.setattr(fleet.loop.managers.tenancy, "tenant_expired", expired)
    assert await models.purge_tenant(fleet.owner) == 3, "a pin, a choice, and a fill set"
    assert await models.purge_tenant(fleet.owner) == 0
    with pytest.raises(NotFound):
        await fleet.matrix.matrix.get_pin(fleet.owner, session_id)
    assert await fleet.matrix.matrix.get_choices(fleet.owner) == ()
