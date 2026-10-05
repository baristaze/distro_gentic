"""The platform assistant's readers over Postgres: each reads through the
asking person's own context, so another tenant's session, project,
automation, and runs, and a session marked deleted, all read as not
found, and no list shows another tenant's row; and asked why a session is
parked on a held call, the assistant reads it and answers with the call
and who may decide it, from what it read."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from contracts.automation_storage import make_automation, make_run
from contracts.loops import reply, said
from contracts.platform_agents import Later, Platform, calls, platform_over
from contracts.project_storage import in_project

from acme.integrations.model_providers.calls import ModelCall, ModelReply
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import new_id, utcnow
from acme.om.context import AppContext, AppType, RequestContext, Role, TenantContext
from acme.om.platform_agents import kinds
from acme.om.steps.types.content import TextBlock, ToolResultBlock
from acme.om.steps.types.header import LoopOutcome, ParkReason, ToolFailure
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.tools.types.policy import ApproverRule, PolicyLayer, ToolPolicy
from acme.om.tools.types.tool import ToolClass

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")

CLERK = AgentKind(
    name="clerk",
    version=1,
    tools=(kinds.SEARCH_CORPUS,),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
    prompts=("Look it up.",),
    policy=PolicyLayer(),  # it allows nothing, so its every call waits for a person
    isolation=NO_WORKSPACE,
)


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


async def a_tenant(platform: Platform, name: str) -> TenantContext:
    slug = f"{name.lower()}-{new_id().hex[-8:]}"
    owner, _ = await platform.managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP), name, slug, f"ann-{slug}@x.test", "Ann"
    )
    return owner


async def a_session(platform: Platform, owner: TenantContext, kind: str = kinds.ENGINEER) -> UUID:
    start = Start(id=new_id(), kind=kind, title="the weekly report")
    return (await platform.managers.agents.start_session(owner, start)).id


async def an_automation(platform: Platform, owner: TenantContext) -> UUID:
    """An automation of the tenant's, with one run on record."""
    automations = platform.storage.get_automation_storage()
    automation = make_automation()
    assert await automations.create_automation(owner.org_id, automation, ())
    await automations.create_run(owner.org_id, make_run(automation.id))
    return automation.id


def not_found(answer: tuple[ToolFailure | None, str]) -> bool:
    failure, text = answer
    return failure is not None and "not found" in text.lower()


# Check: each reader answers only what the asking person may read.


async def test_each_reader_reads_only_the_asking_persons_tenant(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    platform = platform_over(tmp_path, storage=storage)
    platform.owner = await a_tenant(platform, "Ajax")
    other = await a_tenant(platform, "Bolt")
    projects = storage.get_project_storage()
    # Another tenant's session, project, and automation with its run.
    theirs = await a_session(platform, other)
    their_project = await in_project(projects, other.org_id, theirs)
    their_automation = await an_automation(platform, other)
    # The asking person's own, and a session of theirs marked deleted.
    ours = await a_session(platform, platform.owner)
    our_project = await in_project(projects, platform.owner.org_id, ours)
    our_automation = await an_automation(platform, platform.owner)
    deleted = await a_session(platform, platform.owner)
    await platform.managers.agent_sessions.delete_session(platform.owner, deleted)
    asking = await a_session(platform, platform.owner, kinds.PLATFORM_ASSISTANT)
    await platform.say(asking, "What is going on across the board?")
    platform.anthropic.add(
        reply(
            said("Let me read."),
            calls(kinds.READ_SESSION, "their_session", session_id=str(theirs)),
            calls(kinds.READ_WAIT, "their_wait", session_id=str(theirs)),
            calls(kinds.READ_PROJECT, "their_project", project_id=str(their_project)),
            calls(kinds.READ_AUTOMATION, "their_automation", automation_id=str(their_automation)),
            calls(kinds.READ_SESSION, "deleted", session_id=str(deleted)),
            calls(kinds.LIST_SESSIONS, "sessions", limit=50),
            calls(kinds.LIST_SESSIONS, "by_project", project_id=str(their_project)),
            calls(kinds.LIST_PROJECTS, "projects", limit=50),
            calls(kinds.LIST_AUTOMATIONS, "automations", limit=50),
        ),
        reply(
            calls(kinds.READ_SESSION, "our_session", session_id=str(ours)),
            calls(kinds.READ_WAIT, "our_wait", session_id=str(ours)),
            calls(kinds.READ_PROJECT, "our_project", project_id=str(our_project)),
            calls(kinds.READ_AUTOMATION, "our_automation", automation_id=str(our_automation)),
        ),
        reply(said("Here is what your team has.")),
    )

    run = await platform.managers.loop.run(platform.owner, asking)

    assert run.outcome is LoopOutcome.SUCCEEDED
    for use_id in ("their_session", "their_wait", "their_project", "their_automation", "deleted"):
        assert not_found(await platform.answer(asking, use_id)), use_id
    listed: dict[str, set[str]] = {}
    for use_id, field, key in (
        ("sessions", "sessions", "session_id"),
        ("by_project", "sessions", "session_id"),
        ("projects", "projects", "project_id"),
        ("automations", "automations", "automation_id"),
    ):
        failure, text = await platform.answer(asking, use_id)
        assert failure is None, use_id
        listed[use_id] = {row[key] for row in json.loads(text)[field]}
    assert str(ours) in listed["sessions"] and str(asking) in listed["sessions"]
    assert not {str(theirs), str(deleted)} & listed["sessions"]
    assert listed["by_project"] == set()
    assert listed["projects"] == {str(our_project)}
    assert listed["automations"] == {str(our_automation)}
    # The same readers read the person's own tenant whole.
    failure, text = await platform.answer(asking, "our_session")
    assert failure is None and json.loads(text)["project_id"] == str(our_project)
    failure, text = await platform.answer(asking, "our_wait")
    assert failure is None and json.loads(text)["runs_in"] == "cloud"
    failure, text = await platform.answer(asking, "our_project")
    assert failure is None and json.loads(text)["repository"] == "github.com/octo/reports"
    failure, text = await platform.answer(asking, "our_automation")
    read = json.loads(text)
    assert failure is None and [r["status"] for r in read["runs"]] == ["refused"]


# Check: asked why a session is parked on a held call, the assistant reads it
# and answers with the held call and who may decide it.


def from_the_read(use_id: str) -> Later:
    """The assistant's answer, made from what read_session answered and from
    nothing else: a held call the read did not carry is in no answer."""

    def turn(call: ModelCall) -> ModelReply:
        for message in call.messages:
            for block in message.blocks:
                if isinstance(block, ToolResultBlock) and block.tool_use_id == use_id:
                    text = "".join(p.text for p in block.parts if isinstance(p, TextBlock))
                    state = json.loads(text)
                    held = state["held_calls"]
                    parts = [
                        f"It waits for a decision on its call to {c['tool']} "
                        f"(a {c['authorization_class']} call), which a person with the role "
                        f"{' or '.join(c['decided_by'])} may approve or deny on the session's page."
                        for c in held
                    ]
                    return reply(said(" ".join(parts) or "It holds no call."))
        raise AssertionError(f"the model never read {use_id}")

    return turn


async def test_the_assistant_explains_a_held_call_from_what_it_read(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    platform = platform_over(tmp_path, storage=storage, kinds=(CLERK,))
    platform.owner = await a_tenant(platform, "Ajax")
    now = utcnow()
    policy = ToolPolicy(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=platform.owner.user_id,
        updated_by=platform.owner.user_id,
        approvers=(ApproverRule(authorization_class=ToolClass.READ, roles=(Role.ADMIN,)),),
    )
    await platform.managers.tools.write_policy(platform.owner, policy)
    held = await a_session(platform, platform.owner, CLERK.name)
    await platform.say(held, "Look up why sessions wait.")
    platform.anthropic.add(reply(calls(kinds.SEARCH_CORPUS, "use_lookup", query="wait")))
    await platform.managers.loop.run(platform.owner, held)
    session = await platform.managers.agent_sessions.get_session(platform.owner, held)
    assert session.park is not None and session.park.reason is ParkReason.PERSON

    asking = await a_session(platform, platform.owner, kinds.PLATFORM_ASSISTANT)
    await platform.say(asking, f"Why is session {held} parked?")
    platform.anthropic.add(
        reply(calls(kinds.READ_SESSION, "use_read", session_id=str(held))),
        from_the_read("use_read"),
    )

    run = await platform.managers.loop.run(platform.owner, asking)

    assert run.outcome is LoopOutcome.SUCCEEDED
    failure, text = await platform.answer(asking, "use_read")
    state = json.loads(text)
    assert failure is None
    assert (state["status"], state["park_reason"], state["unlock"]) == (
        "parked",
        "person",
        "approval",
    )
    [call] = state["held_calls"]
    assert (call["tool"], call["authorization_class"], call["decided_by"]) == (
        kinds.SEARCH_CORPUS,
        "read",
        ["admin"],
    )
    said_last = [step.as_text() for step in await platform.history(asking) if step.as_text()]
    assert "search_corpus" in said_last[-1] and "admin" in said_last[-1]
