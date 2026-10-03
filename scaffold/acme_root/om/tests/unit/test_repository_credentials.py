"""The two credentials the platform reaches a project's repository with, and
the agent never holds, over the memory roots and the forge's twin. A push
token writes its session's own branch, its snapshots, and its pull request
alone, and ends with its loop's workspace or its lifetime; the engineer
opens its branch and pull request with one it never sees, and both are
its session's work: the events on them find it. A fetch credential is
kept in the tenant's store under its project, handed to the read of a
session's work product alone, and goes with its tenant."""

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from contracts.loops import Loop, live, loop_over, reply, said
from contracts.platform_agents import CORPUS, calls
from contracts.workspaces import REPOSITORY, GitTwin, ProjectsTwin, ReaderTwin
from pydantic import SecretStr

from acme.infra.transports import CommandSpec
from acme.infra.transports.twin import TransportTwinImpl, TwinReply
from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.integrations.events import OpenedPullRequest
from acme.integrations.events.twin import IntegrationTwinImpl
from acme.om.agents.types.result import Claim
from acme.om.automations.root import build_automations
from acme.om.automations.types.automation import (
    Action,
    ActionKind,
    Automation,
    Firing,
    Limits,
    Refusal,
    RunStatus,
    Trigger,
    TriggerKind,
)
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.context import AppContext, AppType, CredentialKind, RequestContext, Role, build_context
from acme.om.evidence.types.provenance import Provenance
from acme.om.exceptions import NotAuthorized, NotFound, Unavailable, ValidationFailed
from acme.om.intake.root import build_intake
from acme.om.intake.rules import described
from acme.om.intake.types.event import (
    Arrival,
    Author,
    AuthorKind,
    CheckState,
    FeedbackEvent,
    WorkNames,
)
from acme.om.intake.types.route import Effect
from acme.om.platform_agents import kinds
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.kinds import ENGINEER_KIND
from acme.om.steps.types.content import TextBlock, ToolResultBlock
from acme.om.steps.types.header import ParkReason, ToolFailure, ToolResponseHeader
from acme.om.steps.types.step import StepType
from acme.om.tenancy.rules import permissions_of
from acme.om.workspaces import rules
from acme.om.workspaces.impl.forge import SourceControlForgeImpl
from acme.om.workspaces.impl.manager import WorkspacesOptions
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import RepositoryBinding, RepositoryWrite, WriteKind
from acme.om.workspaces.types.workspace import SessionWorkspace

TWIN = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.NONE))
ENGINEER = ENGINEER_KIND.model_copy(
    update={"version": ENGINEER_KIND.version + 1, "isolation": TWIN}
)
"""The shipped engineer, whole, in the workspace this suite can prepare."""

HEAD = "c" * 40
PASSWORD = "fetch-only-0123456789"
WORKER = AppContext(type=AppType.WORKER, version="worker@test")


class Forged:
    """An engineer's platform: its project binds `REPOSITORY`, the forge is
    the integration's twin, the workspace's HEAD is `HEAD`, and intake binds
    a session's work as the session runner wires it."""

    def __init__(self, tmp_path: Path, **roots: Any) -> None:
        self.forge = IntegrationTwinImpl("forge")
        self.projects = ProjectsTwin()
        self.reader = ReaderTwin(head=HEAD)
        self.loop: Loop = loop_over(
            tmp_path,
            kinds=(ENGINEER,),
            platform_agents=PlatformAgents(corpus=CORPUS),
            intake=lambda: self.intake,
            workspace_projects=self.projects,
            workspace_git=GitTwin(head=HEAD),
            workspace_reader=self.reader,
            source_control=SourceControlForgeImpl(lambda name: self.forge, self.tenant_of),
            **roots,
        )
        self.intake = build_intake(self.loop.storage, self.loop.managers, principal_context=live)
        self.service = build_context(
            RequestContext(request_id=new_id(), app=WORKER),
            user_id=EMPTY_UUID,
            org_id=self.loop.owner.org_id,
            role=Role.SERVICE,
            permissions=permissions_of(Role.SERVICE),
            credential_kind=CredentialKind.INTERNAL,
        )
        transport = self.loop.infra.get_transport()
        assert isinstance(transport, TransportTwinImpl)
        self.commands: list[tuple[str, ...]] = []

        async def checkout(command: CommandSpec, env: Mapping[str, str]) -> TwinReply:
            self.commands.append(command.argv)
            if command.argv[:2] == ("git", "rev-parse"):
                return TwinReply(stdout=f"{self.head}\n")
            return TwinReply()

        self.head = HEAD
        transport.handler = checkout

    async def tenant_of(self, integration: str, installation: str) -> UUID | None:
        """The engineer's tenant connected the forge's installation."""
        return self.loop.owner.org_id

    async def engineer(self) -> UUID:
        return await self.loop.start(kinds.ENGINEER)

    async def held(self, session_id: UUID) -> SessionWorkspace:
        return await self.loop.managers.workspaces.get_workspace(self.loop.owner, session_id)

    async def answer(self, session_id: UUID, use_id: str) -> tuple[ToolFailure | None, str]:
        for step in await self.loop.history(session_id):
            if step.type is not StepType.TOOL_RESPONSE:
                continue
            for block in step.content.blocks:
                if isinstance(block, ToolResultBlock) and block.tool_use_id == use_id:
                    header = step.header
                    assert isinstance(header, ToolResponseHeader)
                    texts = [p.text for p in block.parts if isinstance(p, TextBlock)]
                    return header.failure, "\n".join(texts)
        raise AssertionError(f"no answer to {use_id}")


def held_with(digest: str | None, expires_in: timedelta) -> SessionWorkspace:
    now = utcnow()
    return SessionWorkspace(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        project_id=new_id(),
        level=IsolationMode.TWIN,
        egress=EgressMode.NONE,
        egress_source="its kind's",
        branch="sessions/one",
        push_digest=digest,
        push_expires_at=now + expires_in,
    )


# Check 2: the engineer's branch and pull request open with a token scoped
# to that branch, and the token cannot push another branch or outlive its
# session's loop.


def test_a_push_token_writes_its_sessions_branch_and_pull_request_alone() -> None:
    held = held_with("d1", timedelta(minutes=5))
    assert held.project_id is not None
    binding = RepositoryBinding(project_id=held.project_id, repository=REPOSITORY)
    now = utcnow()

    def push(ref: str, repository: str = REPOSITORY) -> RepositoryWrite:
        return RepositoryWrite(repository=repository, kind=WriteKind.PUSH, ref=ref)

    own = (
        push("refs/heads/sessions/one"),
        push(f"{rules.SNAPSHOT_PREFIX}/sessions/one/20261003T000000000000Z"),
        RepositoryWrite(repository=REPOSITORY, kind=WriteKind.PULL_REQUEST, ref="sessions/one"),
    )
    for write in own:
        assert rules.push_refusal(held, binding, "d1", write, now) is None, write.ref

    elsewhere = (
        push("refs/heads/main"),
        push("refs/heads/sessions/another"),
        push(f"{rules.SNAPSHOT_PREFIX}/sessions/another/20261003T000000000000Z"),
        push("refs/heads/sessions/one", repository="https://git.example.com/ajax/other.git"),
        RepositoryWrite(repository=REPOSITORY, kind=WriteKind.PULL_REQUEST, ref="main"),
        RepositoryWrite(repository=REPOSITORY, kind=WriteKind.OTHER, ref="sessions/one"),
    )
    for write in elsewhere:
        refusal = rules.push_refusal(held, binding, "d1", write, now)
        assert refusal is not None and "alone" in refusal, write

    branch = own[0]
    assert "live token" in str(rules.push_refusal(held, binding, "d2", branch, now))
    revoked = held.model_copy(update={"push_digest": None})
    assert "live token" in str(rules.push_refusal(revoked, binding, "d1", branch, now))
    expired = held_with("d1", timedelta(seconds=-1))
    assert "expired" in str(rules.push_refusal(expired, binding, "d1", branch, now))
    assert rules.push_refusal(held, None, "d1", branch, now) is not None, "no repository"


async def test_the_engineer_opens_its_branch_and_pull_request_with_a_token_it_never_sees(
    tmp_path: Path,
) -> None:
    platform = Forged(tmp_path)
    session_id = await platform.engineer()
    await platform.loop.say(session_id, "The weekly report misses its total. Fix it.")
    platform.loop.anthropic.add(
        reply(calls(kinds.OPEN_PULL_REQUEST, "use_pr", title="Add the total", body="It adds.")),
        reply(calls(kinds.SUBMIT_RESULT, "use_done", claim=Claim.SUCCEEDED.value, evidence=[])),
    )
    await platform.loop.managers.loop.run(platform.loop.owner, session_id)

    failure, text = await platform.answer(session_id, "use_pr")
    branch = rules.session_branch(session_id)
    assert failure is None, text
    assert platform.forge.refs == {(REPOSITORY, f"refs/heads/{branch}"): HEAD}, "its own branch"
    (opened,) = platform.forge.pull_requests
    assert (opened.repository, opened.head, opened.title) == (REPOSITORY, branch, "Add the total")
    assert opened.url in text and branch in text
    held = await platform.held(session_id)
    assert held.push_digest is None, "the loop's workspace went, and its token with it"
    history = "".join(step.model_dump_json() for step in await platform.loop.history(session_id))
    assert rules.PUSH_TOKEN_PREFIX not in history, "the token is in no step the model reads"
    assert all(rules.PUSH_TOKEN_PREFIX not in " ".join(argv) for argv in platform.commands)


async def test_a_workspace_with_no_commit_opens_nothing(tmp_path: Path) -> None:
    platform = Forged(tmp_path)
    platform.head = "not a commit\nrefs/heads/main"
    session_id = await platform.engineer()
    await platform.loop.say(session_id, "Fix it.")
    platform.loop.anthropic.add(
        reply(calls(kinds.OPEN_PULL_REQUEST, "use_pr", title="Add the total")),
        reply(calls(kinds.SUBMIT_RESULT, "use_done", claim=Claim.FAILED.value, evidence=[])),
    )
    await platform.loop.managers.loop.run(platform.loop.owner, session_id)
    failure, text = await platform.answer(session_id, "use_pr")
    assert failure is ToolFailure.PERMANENT and "commit first" in text
    assert platform.forge.refs == {} and platform.forge.pull_requests == []


# The engineer's branch and pull request are its session's work: a comment
# or a person's push on either finds the session, and what follows from its
# push names the session as its cause.


async def opened(platform: Forged, session_id: UUID) -> OpenedPullRequest:
    """The engineer opens its pull request and ends its turn; answers the
    pull request as the forge holds it."""
    platform.loop.anthropic.add(
        reply(calls(kinds.OPEN_PULL_REQUEST, "use_pr", title="Add the total")),
        reply(said("Opened.")),
    )
    await platform.loop.managers.loop.run(platform.loop.owner, session_id)
    failure, text = await platform.answer(session_id, "use_pr")
    assert failure is None, text
    (pull_request,) = platform.forge.pull_requests
    return pull_request


def from_forge(
    arrival: Arrival,
    author: AuthorKind,
    names: WorkNames,
    *,
    refs: tuple[str, ...] = (),
    check: CheckState | None = None,
    text: str = "",
) -> FeedbackEvent:
    who = "ann" if author is AuthorKind.PERSON else "ci"
    return FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=arrival,
        author=Author(kind=author, external_id=who, name=who),
        names=names,
        refs=refs,
        check=check,
        text=text,
        occurred_at=utcnow(),
    )


async def test_a_comment_on_the_engineers_pull_request_reaches_its_session(
    tmp_path: Path,
) -> None:
    platform = Forged(tmp_path)
    session_id = await platform.engineer()
    await platform.loop.say(session_id, "The weekly report misses its total. Fix it.")
    pull_request = await opened(platform, session_id)
    comment = from_forge(
        Arrival.COMMENT,
        AuthorKind.PERSON,
        WorkNames(pull_request=pull_request.id),
        text="Name the column Total.",
    )
    routed = await platform.intake.route(platform.service, comment)
    assert (routed.session_id, routed.effect) == (session_id, Effect.WAKE_AS_DATA)
    landed = [s for s in await platform.loop.history(session_id) if s.id == routed.step_id]
    assert len(landed) == 1 and "Name the column Total." in landed[0].model_dump_json()


async def test_a_persons_push_to_the_engineers_branch_hands_its_session_over(
    tmp_path: Path,
) -> None:
    platform = Forged(tmp_path)
    session_id = await platform.engineer()
    await platform.loop.say(session_id, "The weekly report misses its total. Fix it.")
    await opened(platform, session_id)
    branch = WorkNames(branch=rules.session_branch(session_id))
    routed = await platform.intake.route(
        platform.service, from_forge(Arrival.PUSH, AuthorKind.PERSON, branch)
    )
    assert (routed.session_id, routed.effect) == (session_id, Effect.HAND_OVER)
    held = await platform.loop.managers.agent_sessions.get_session(platform.loop.owner, session_id)
    assert held.park is not None and held.park.reason is ParkReason.HANDOVER


def automation_named(name: str) -> Automation:
    now = utcnow()
    dollar = 1_000_000  # micros
    return Automation(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=new_id(),
        updated_by=new_id(),
        name=name,
        trigger=Trigger(kind=TriggerKind.EVENT),
        action=Action(
            kind=ActionKind.START_SESSION,
            brief="Fix what the event reports.",
            agent_kind=kinds.ENGINEER,
            title=name,
        ),
        limits=Limits(
            cost_cap_micros=1000 * dollar, run_cap_micros=50 * dollar, rate=10, concurrency=10
        ),
    )


@pytest.mark.parametrize("named_by", ["its_branch", "its_commit_alone"])
async def test_a_check_on_the_engineers_push_follows_its_session_a_hop_on(
    tmp_path: Path, named_by: str
) -> None:
    """An automation starts the engineer, and CI fails on what it pushed.
    The check names the engineer's branch, or only the commit the
    platform's account pushed for it. Either way its cause is the
    engineer's session, and the automation it feeds fires a hop past the
    run that started that session."""
    platform = Forged(tmp_path)
    automations = build_automations(
        platform.loop.storage,
        platform.loop.managers,
        project_required=False,
        principal_context=live,
    )
    owner = platform.loop.owner
    starter = await automations.create_automation(owner, automation_named("starter"))
    report = Firing(
        event_id=new_id(),
        occurred_at=utcnow(),
        integration="forge",
        arrival=Arrival.TICKET.value,
        effect=Effect.WAKE_AS_DATA.value,
        text="The weekly report misses its total.",
    )
    (first,) = await automations.fire(platform.service, report)
    assert first.session_id is not None and first.hop == 1
    other = await automations.create_automation(owner, automation_named("other"))
    await opened(platform, first.session_id)

    if named_by == "its_branch":
        names, refs = WorkNames(branch=rules.session_branch(first.session_id)), ()
    else:
        names, refs = WorkNames(), (HEAD,)
    check = from_forge(
        Arrival.CHECK,
        AuthorKind.BOT,
        names,
        refs=refs,
        check=CheckState.FAILED,
        text="tests failed",
    )
    routed = await platform.intake.route(platform.service, check)
    assert routed.caused_by == first.session_id
    firing = Firing(
        event_id=check.id,
        occurred_at=check.occurred_at,
        integration=check.integration,
        arrival=check.arrival.value,
        effect=routed.effect.value,
        caused_by=routed.caused_by,
        platform=routed.platform,
        text=described(check),
    )
    runs = {run.automation_id: run for run in await automations.fire(platform.service, firing)}
    assert runs[starter.id].refusal is Refusal.OWN_EVENT
    fed = runs[other.id]
    assert (fed.status, fed.caused_by, fed.hop) == (RunStatus.STARTED, first.session_id, 2)


async def test_a_push_token_cannot_push_another_sessions_branch_or_outlive_its_loop(
    tmp_path: Path,
) -> None:
    lifetime = timedelta(minutes=7)
    platform = Forged(tmp_path, workspaces_options=WorkspacesOptions(push_token_lifetime=lifetime))
    workspaces, owner = platform.loop.managers.workspaces, platform.loop.owner
    one, other = await platform.engineer(), await platform.engineer()
    before = utcnow()
    token = await workspaces.mint_push_token(owner, one)
    assert token.token.get_secret_value().startswith(rules.PUSH_TOKEN_PREFIX)
    assert (token.repository, token.branch) == (REPOSITORY, rules.session_branch(one))
    assert before + lifetime <= token.expires_at <= utcnow() + lifetime, "its lifetime at most"
    value = token.token.get_secret_value()

    with pytest.raises(NotAuthorized, match="live token"):
        await workspaces.open_pull_request(owner, other, value, HEAD, "t", "")
    await workspaces.mint_push_token(owner, other)
    with pytest.raises(NotAuthorized, match="live token"):
        await workspaces.open_pull_request(owner, other, value, HEAD, "t", "")
    assert platform.forge.refs == {}, "another session's branch is never written"

    # A prepare of the loop's workspace ends the token, and so does a release.
    workspace = await platform.loop.managers.tools.prepare_workspace(owner, one, TWIN)
    with pytest.raises(NotAuthorized, match="live token"):
        await workspaces.open_pull_request(owner, one, value, HEAD, "t", "")
    again = (await workspaces.mint_push_token(owner, one)).token.get_secret_value()
    await platform.loop.managers.tools.release_workspace(owner, workspace)
    assert (await platform.held(one)).push_digest is None
    with pytest.raises(NotAuthorized, match="live token"):
        await workspaces.open_pull_request(owner, one, again, HEAD, "t", "")
    assert platform.forge.refs == {} and platform.forge.pull_requests == []

    live = (await workspaces.mint_push_token(owner, one)).token.get_secret_value()
    replaced = (await workspaces.mint_push_token(owner, one)).token.get_secret_value()
    with pytest.raises(NotAuthorized, match="live token"):
        await workspaces.open_pull_request(owner, one, live, HEAD, "t", "")
    # The commits go out of the workspace this host holds, and of no other.
    with pytest.raises(Unavailable, match="not held here"):
        await workspaces.open_pull_request(owner, one, replaced, HEAD, "t", "")
    await platform.loop.managers.tools.prepare_workspace(owner, one, TWIN)
    newest = (await workspaces.mint_push_token(owner, one)).token.get_secret_value()
    opened = await workspaces.open_pull_request(owner, one, newest, HEAD, "t", "")
    assert platform.forge.pull_requests[0].id == opened.id, "the newest token alone"
    branch = f"refs/heads/{rules.session_branch(one)}"
    assert platform.forge.refs == {(REPOSITORY, branch): HEAD}, "its own branch alone"
    assert (await platform.held(one)).branch_seen, "the platform pushed it, so it knows it"


# The forge renders the body the agent writes: nothing in it makes the
# forge, or a surface that mirrors it, fetch a URL the agent chose.


@pytest.mark.parametrize(
    "body",
    [
        "![status](https://tracker.invalid/pixel.png)",
        '<img src="https://tracker.invalid/pixel.png">',
        '<picture><source srcset="https://tracker.invalid/p.png"></picture>',
        "See [the log](https://tracker.invalid/log).",
        "See <//tracker.invalid/log>.",
        "See [the log](https&#58;//tracker.invalid/log).",
        "See www.tracker.invalid.",
    ],
)
async def test_a_pull_request_body_that_makes_the_forge_fetch_elsewhere_is_refused(
    tmp_path: Path, body: str
) -> None:
    platform = Forged(tmp_path)
    workspaces, owner = platform.loop.managers.workspaces, platform.loop.owner
    one = await platform.engineer()
    await platform.loop.managers.tools.prepare_workspace(owner, one, TWIN)
    token = (await workspaces.mint_push_token(owner, one)).token.get_secret_value()

    with pytest.raises(ValidationFailed, match="pull request's body"):
        await workspaces.open_pull_request(owner, one, token, HEAD, "t", body)

    assert platform.forge.refs == {} and platform.forge.pull_requests == [], "nothing written"
    own = "Fixes the total. See https://git.example.com/ajax/app/pull/1.\n\n`a // b`"
    await workspaces.open_pull_request(owner, one, token, HEAD, "t", own)
    assert [opened.body for opened in platform.forge.pull_requests] == [own]


# A fetch credential is the tenant's, kept under its project, and reaches
# the read of a session's work product alone.


async def test_a_fetch_credential_is_kept_in_the_store_and_reaches_the_read_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = Forged(tmp_path)
    workspaces, owner = platform.loop.managers.workspaces, platform.loop.owner
    project_id = platform.projects.project_id
    secrets = platform.loop.infra.get_secrets()
    credential = FetchCredential(username="reader", password=SecretStr(PASSWORD))
    with pytest.raises(NotAuthorized):
        await workspaces.put_fetch_credential(platform.loop.colleague(), project_id, credential)
    with pytest.raises(NotFound):
        await workspaces.put_fetch_credential(owner, new_id(), credential)

    record = await workspaces.put_fetch_credential(owner, project_id, credential)
    assert (record.id, record.version) == (project_id, 1)
    assert PASSWORD not in record.model_dump_json(), "the record holds no value"
    kept = await secrets.get(owner.org_id, rules.fetch_secret_name(project_id))
    assert FetchCredential.model_validate_json(kept) == credential
    rotated = FetchCredential(username="reader", password=SecretStr("rotated"))
    assert (await workspaces.put_fetch_credential(owner, project_id, rotated)).version == 2

    session_id = await platform.engineer()
    workspace = await platform.loop.managers.tools.prepare_workspace(owner, session_id, TWIN)
    await workspaces.delivery(owner, workspace)
    assert platform.reader.credentials == [rotated], "handed to the read of the work product"
    held = await platform.held(session_id)
    assert "rotated" not in held.model_dump_json(), "never on the session's workspace"

    async def expired(ctx: object) -> bool:
        return True

    monkeypatch.setattr(platform.loop.managers.tenancy, "tenant_expired", expired)
    assert await workspaces.purge_tenant(owner) >= 2
    assert not await secrets.has(owner.org_id, rules.fetch_secret_name(project_id))
    platform.reader.credentials.clear()
    with pytest.raises(NotFound):
        await workspaces.get_workspace(owner, session_id)


async def test_a_fetch_credential_whose_value_left_the_store_reads_nothing(
    tmp_path: Path,
) -> None:
    platform = Forged(tmp_path)
    workspaces, owner = platform.loop.managers.workspaces, platform.loop.owner
    project_id = platform.projects.project_id
    credential = FetchCredential(username="reader", password=SecretStr(PASSWORD))
    await workspaces.put_fetch_credential(owner, project_id, credential)
    await platform.loop.infra.get_secrets().delete(
        owner.org_id, rules.fetch_secret_name(project_id)
    )

    session_id = await platform.engineer()
    with pytest.raises(Unavailable, match="is gone"):
        await platform.loop.managers.tools.prepare_workspace(owner, session_id, TWIN)
    assert platform.reader.credentials == [], "no read without the value"
    assert platform.reader.brought == [], "and no checkout"
