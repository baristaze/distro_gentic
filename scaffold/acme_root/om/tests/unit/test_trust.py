"""Trust, as the platform runs it: a call's audit entry holds its four
answers apart; a steady session whose principal left parks its calls until
a person takes it over; a secret's value reaches no step, no log, no
stream part, and no model, and a secret never crosses its session's wall;
a tenant's key rotates by reference, so no client serves a rotated one."""

import logging
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.doubles import context
from contracts.factories import make_org
from contracts.loops import reply, said, use
from contracts.tools import INJECTED_TOKEN, echoing
from contracts.trust import Trusted, trusted

from acme.infra.transports.redaction import forms, marker
from acme.integrations.model_providers.absent import ModelProviderAbsentImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.agents.loop_rules import PRINCIPAL_UNLOCK
from acme.om.agents.types.run import RunEnd
from acme.om.attribution.types.principal import AgentRef, Principal, PrincipalKind
from acme.om.base import new_id, utcnow
from acme.om.context import Role
from acme.om.exceptions import NotAuthorized, NotFound
from acme.om.steps.types.content import ToolResultBlock, ToolUseBlock
from acme.om.steps.types.header import LoopOutcome, ParkReason, ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import Actor, Step, StepType
from acme.om.tools.impl.manager import SECRET_USED
from acme.om.trust.exceptions import KeyRefused, SecretCrossesWall
from acme.om.trust.impl.keys import ProviderClientsCachedImpl
from acme.om.trust.impl.manager import CALL_AUDITED
from acme.om.trust.types.identities import (
    ActorRef,
    CallAudit,
    Executor,
    ExecutorKind,
)
from acme.om.trust.types.provider_key import KeyStatus, key_secret_name
from acme.om.trust.types.secret import SecretDeclaration, SecretOwnerKind, SecretStore

SECRET = "ghs_4b1d9e7c2a6f80c3-deploy"


def person(user_id: UUID) -> Principal:
    return Principal(kind=PrincipalKind.PERSON, id=user_id)


def call(name: str) -> ToolUseBlock:
    """A call of `lookup`, or of `call_api` with the command it runs."""
    if name == "call_api":
        return ToolUseBlock(
            id=f"use_{name}_{new_id().hex[:8]}", name=name, input={"argv": ["fetch", "records"]}
        )
    return use(name, use_id=f"use_{name}_{new_id().hex[:8]}")


def of_type(steps: list[Step], step_type: StepType) -> list[Step]:
    return [step for step in steps if step.type is step_type]


async def audits(platform: Trusted) -> list[CallAudit]:
    events = await platform.managers.events.get_events(platform.owner, 0, 500)
    return [CallAudit.model_validate(e.payload) for e in events if e.kind == CALL_AUDITED]


def declared(
    name: str = INJECTED_TOKEN.name, store: SecretStore = SecretStore.CLOUD
) -> SecretDeclaration:
    """A declaration as a caller sends it: the manager stamps who and when."""
    now = utcnow()
    return SecretDeclaration(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        name=name,
        variable=INJECTED_TOKEN.env or "",
        owner_kind=SecretOwnerKind.PROJECT,
        owner_id=new_id(),
        scope="call:records-api",
        store=store,
    )


# Check 1: an audit entry names executor, principal, spender, and actor, and
# no two of them are one.


async def test_a_calls_audit_entry_holds_its_four_answers_apart(tmp_path: Path) -> None:
    platform = trusted(tmp_path)
    session_id = await platform.start()
    platform.placement.walled.add(session_id)
    asker = platform.member()
    await platform.say(session_id, "Find the total.", asker)
    platform.anthropic.add(reply(said("Looking."), call("lookup")), reply(said("It is 12.")))

    run = await platform.loops.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    (audit,) = await audits(platform)
    (request,) = of_type(await platform.history(session_id), StepType.TOOL_REQUEST)
    assert audit.request_id == request.id and audit.tool == "lookup"
    # The machine that ran it, whom it ran under, who paid, and who acted:
    # each from its own source, and no two the same.
    assert audit.executor == platform.placement.host
    assert audit.principal == person(platform.owner.user_id), "steady: its starter's authority"
    assert audit.spender == person(asker.user_id), "the person who asked pays"
    assert audit.actor == ActorRef(
        actor=Actor.AGENT, agent=AgentRef(kind="steady", version=1, session_id=session_id)
    )
    answers = [
        audit.executor.credential_id,
        audit.principal.id,
        audit.spender.id,
        audit.actor.agent.session_id if audit.actor.agent else None,
    ]
    assert len(set(answers)) == 4
    assert platform.lookup.ran_as == [platform.owner.user_id]


async def test_an_audit_entry_refuses_one_answer_in_two_fields() -> None:
    session_id, payer = new_id(), person(new_id())
    agent = ActorRef(
        actor=Actor.AGENT, agent=AgentRef(kind="steady", version=1, session_id=session_id)
    )
    whole = {
        "request_id": new_id(),
        "session_id": session_id,
        "tool": "lookup",
        "executor": Executor(kind=ExecutorKind.HOST, credential_id=new_id(), label="lab-host-1"),
        "principal": person(new_id()),
        "spender": payer,
        "actor": agent,
    }
    CallAudit.model_validate(whole)
    machine_as_person = Executor(kind=ExecutorKind.HOST, credential_id=payer.id, label="lab-host-1")
    principal_as_actor = ActorRef(actor=Actor.PERSON)
    elsewhere = ActorRef(
        actor=Actor.AGENT, agent=AgentRef(kind="steady", version=1, session_id=new_id())
    )
    for conflated in (
        {"executor": machine_as_person},
        {"actor": principal_as_actor},
        {"actor": elsewhere},
    ):
        with pytest.raises(ValueError):
            CallAudit.model_validate({**whole, **conflated})


# Check 2: a session whose principal was revoked parks its calls, and runs
# again only once a person takes it over.


async def test_a_lapsed_principal_parks_the_call_until_a_person_takes_the_session_over(
    tmp_path: Path,
) -> None:
    platform = trusted(tmp_path)
    session_id = await platform.start()
    await platform.say(session_id, "Find the total.")
    platform.anthropic.add(reply(said("Looking."), call("lookup")))
    platform.transition.revoked.add(platform.owner.user_id)

    parked = await platform.loops.run(platform.owner, session_id)

    assert parked.end is RunEnd.PARKED and parked.park is not None
    assert (parked.park.reason, parked.park.unlock) == (ParkReason.PERSON, PRINCIPAL_UNLOCK)
    assert platform.lookup.ran_as == [] and await audits(platform) == []

    # A message from someone else lends the call no authority: the session
    # stays parked, and a run takes nothing up.
    other = platform.member()
    await platform.say(session_id, "Please go on.", other)
    again = await platform.loops.run(platform.owner, session_id)
    assert again.end is RunEnd.IDLE
    session = await platform.managers.agent_sessions.get_session(platform.owner, session_id)
    assert session.park is not None and session.park.unlock == PRINCIPAL_UNLOCK
    assert platform.lookup.ran_as == []

    # A viewer takes nothing over.
    with pytest.raises(NotAuthorized):
        await platform.trust.trust.assign_principal(context(Role.VIEWER, make_org()), session_id)

    taken = await platform.trust.trust.assign_principal(other, session_id)
    assert taken.principal == person(other.user_id)
    platform.anthropic.add(reply(said("It is 12.")))
    resumed = await platform.loops.run(platform.owner, session_id)

    assert resumed.outcome is LoopOutcome.SUCCEEDED
    assert platform.lookup.ran_as == [other.user_id], "under the person who took it over"
    (audit,) = await audits(platform)
    assert audit.principal == person(other.user_id)


# Check 3: a secret's value never appears in a step, a log, a stream part,
# or what a model reads; and a secret never crosses its session's wall.


async def test_a_secrets_value_reaches_no_step_no_log_no_stream_part_and_no_model(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    platform = trusted(tmp_path)
    await platform.trust.trust.declare_secret(platform.owner, declared())
    await platform.trust.trust.put_secret(platform.owner, INJECTED_TOKEN.name, SECRET)
    platform.transport.handler = echoing("API_TOKEN")
    session_id = await platform.start()
    await platform.say(session_id, "Call the records API.")
    platform.anthropic.add(reply(said("Calling."), call("call_api")), reply(said("Done.")))

    run = await platform.loops.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    steps = await platform.history(session_id)
    (answer,) = of_type(steps, StepType.TOOL_RESPONSE)
    (result,) = answer.content.blocks
    assert isinstance(result, ToolResultBlock)
    assert marker(INJECTED_TOKEN.name) in result.parts[0].model_dump_json(), "it ran, redacted"
    events = await platform.managers.events.get_events(platform.owner, 0, 500)
    used = [e for e in events if e.kind == SECRET_USED]
    assert [e.payload["secret"] for e in used] == [INJECTED_TOKEN.name], "audited by name"
    held = [
        *(step.model_dump_json() for step in steps),
        *(event.model_dump_json() for event in events),
        *(part.model_dump_json() for part in platform.sink.parts),
        *(record.getMessage() for record in caplog.records),
        *(repr(record.__dict__) for record in caplog.records),
        *(c.model_dump_json() for c in platform.anthropic.calls),
        *(
            k.model_dump_json()
            for k in await platform.trust.trust.get_secrets(platform.owner, None, 10)
        ),
    ]
    assert platform.sink.parts, "the command's output streamed"
    for text in held:
        for form in forms(SECRET):
            assert form not in text


async def test_a_cloud_secret_is_refused_for_a_session_inside_a_customers_wall(
    tmp_path: Path,
) -> None:
    platform = trusted(tmp_path)
    await platform.trust.trust.declare_secret(platform.owner, declared())
    await platform.trust.trust.put_secret(platform.owner, INJECTED_TOKEN.name, SECRET)
    platform.transport.handler = echoing("API_TOKEN")
    session_id = await platform.start()
    platform.placement.walled.add(session_id)
    await platform.say(session_id, "Call the records API.")
    platform.anthropic.add(reply(said("Calling."), call("call_api")), reply(said("Refused.")))

    run = await platform.loops.run(platform.owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    (answer,) = of_type(await platform.history(session_id), StepType.TOOL_RESPONSE)
    header = answer.header
    assert isinstance(header, ToolResponseHeader) and header.failure is ToolFailure.DENIED
    assert "api_token is a cloud secret" in answer.model_dump_json()
    assert platform.transport.commands == [], "nothing reached a transport"
    assert await audits(platform) == [], "nothing ran"


async def test_a_secret_crosses_no_wall_either_way_and_takes_no_value_from_the_cloud(
    tmp_path: Path,
) -> None:
    platform = trusted(tmp_path)
    trust = platform.trust.trust
    walled, cloud = await platform.start(), await platform.start()
    platform.placement.walled.add(walled)
    # Never declared: resolved from the platform's store, so a cloud secret.
    with pytest.raises(SecretCrossesWall):
        await trust.refuse_crossing(platform.owner, walled, (INJECTED_TOKEN,))
    await trust.refuse_crossing(platform.owner, cloud, (INJECTED_TOKEN,))
    held_inside = await trust.declare_secret(platform.owner, declared(store=SecretStore.HOST))
    await trust.refuse_crossing(platform.owner, walled, (INJECTED_TOKEN,))
    with pytest.raises(SecretCrossesWall):
        await trust.refuse_crossing(platform.owner, cloud, (INJECTED_TOKEN,))
    with pytest.raises(SecretCrossesWall):
        await trust.put_secret(platform.owner, held_inside.name, SECRET)
    assert not await platform.infra.get_secrets().has(platform.owner.org_id, held_inside.name)
    aimed_elsewhere = INJECTED_TOKEN.model_copy(update={"env": "OTHER_TOKEN"})
    with pytest.raises(SecretCrossesWall):
        await trust.refuse_crossing(platform.owner, walled, (aimed_elsewhere,))
    with pytest.raises(ValueError):
        SecretDeclaration.model_validate(
            {**declared().model_dump(), "owner_kind": SecretOwnerKind.STATION}
        )
    with pytest.raises(NotAuthorized):
        await trust.declare_secret(platform.member(), declared(name="another"))


# Check 4: a rotated tenant key is never served from a client cached by its
# old reference.


class KeyedClient(ModelProviderAbsentImpl):
    """A client that remembers the key it was built on, and whether it was
    closed."""

    def __init__(self, provider: ProviderName, value: str) -> None:
        super().__init__(provider, "a test's client")
        self.value = value
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_a_rotated_key_is_never_served_from_a_client_cached_by_its_old_reference(
    tmp_path: Path,
) -> None:
    built: list[KeyedClient] = []

    def factory(provider: ProviderName, value: str) -> KeyedClient:
        built.append(KeyedClient(provider, value))
        return built[-1]

    platform = trusted(tmp_path, clients=factory)
    trust, clients = platform.trust.trust, platform.trust.provider_clients
    owner = platform.owner
    first = await trust.save_provider_key(owner, ProviderName.ANTHROPIC, "sk-first")
    served = await clients.client_for(owner, ProviderName.ANTHROPIC)
    assert served is await clients.client_for(owner, ProviderName.ANTHROPIC), "cached"
    assert isinstance(served, KeyedClient) and served.value == "sk-first"
    # A second process, whose cache took the first key before the rotation.
    elsewhere = ProviderClientsCachedImpl(
        platform.storage.get_trust_storage(),
        platform.infra.get_secrets(),
        factory,
        use_grain=timedelta(minutes=5),
    )
    held_there = await elsewhere.client_for(owner, ProviderName.ANTHROPIC)
    assert isinstance(held_there, KeyedClient) and held_there.value == "sk-first"

    second = await trust.save_provider_key(owner, ProviderName.ANTHROPIC, "sk-second")

    assert second.id != first.id, "a rotation mints a new reference"
    now_served = await clients.client_for(owner, ProviderName.ANTHROPIC)
    assert isinstance(now_served, KeyedClient) and now_served.value == "sk-second"
    assert served.closed, "the old reference's client is dropped and closed"
    there = await elsewhere.client_for(owner, ProviderName.ANTHROPIC)
    assert isinstance(there, KeyedClient) and there.value == "sk-second"
    assert there is not held_there and held_there.closed, "the other process's too"
    secrets = platform.infra.get_secrets()
    assert not await secrets.has(owner.org_id, key_secret_name(first.id)), "its value is gone"
    keys = {k.id: k for k in await trust.get_provider_keys(owner, 10)}
    assert keys[first.id].status is KeyStatus.ROTATED and keys[second.id].status is KeyStatus.LIVE
    assert keys[second.id].created_by == owner.user_id and keys[second.id].last_used_at
    shown = "".join(k.model_dump_json() for k in keys.values())
    assert "sk-first" not in shown and "sk-second" not in shown, "never the value"


async def test_a_key_the_provider_refuses_is_never_saved(tmp_path: Path) -> None:
    platform = trusted(tmp_path)
    trust = platform.trust.trust
    with pytest.raises(KeyRefused):
        await trust.save_provider_key(platform.owner, ProviderName.OPENAI, "sk-refused")
    assert platform.probe.asked == [ProviderName.OPENAI]
    assert await trust.get_provider_keys(platform.owner, 10) == ()
    with pytest.raises(NotFound):
        await platform.trust.provider_clients.client_for(platform.owner, ProviderName.OPENAI)
    with pytest.raises(NotAuthorized):
        await trust.save_provider_key(platform.member(), ProviderName.OPENAI, "sk-member")


async def test_a_purged_tenants_keys_leave_the_store_with_their_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = trusted(tmp_path)
    trust, owner = platform.trust.trust, platform.owner
    key = await trust.save_provider_key(owner, ProviderName.ANTHROPIC, "sk-first")
    await trust.declare_secret(owner, declared())
    assert await trust.purge_tenant(owner) == 0, "a living tenant keeps everything"

    async def expired(ctx: object) -> bool:
        return True

    monkeypatch.setattr(platform.managers.tenancy, "tenant_expired", expired)
    assert await trust.purge_tenant(owner) == 2
    assert not await platform.infra.get_secrets().has(owner.org_id, key_secret_name(key.id))
    assert await trust.get_provider_keys(owner, 10) == ()
    assert await trust.get_secrets(owner, None, 10) == ()
