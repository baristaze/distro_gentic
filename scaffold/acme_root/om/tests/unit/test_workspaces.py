"""A session's workspace as the platform runs it, over the memory roots and
the scripted provider: its isolation pinned when the session is created and
refused by a host that cannot give it, with the loop parked on the
resource; its work pushed before its instance goes, the next loop told, and
a vanished branch failing loudly; its egress its project's allowlist; and
its own branch and pull request its work product."""

from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from contracts.loops import ASSISTANT, Loop, loop_over, reply, said
from contracts.project_storage import make_project
from contracts.workspaces import (
    BASE,
    REPOSITORY,
    GitTwin,
    ProjectsTwin,
    PullRequestsTwin,
    ReaderTwin,
)

from acme.infra.workspaces import (
    EgressMode,
    EgressPolicy,
    IsolationMode,
    IsolationRefused,
    IsolationSpec,
)
from acme.infra.workspaces.twin import WorkspaceTwinImpl
from acme.om.agents import ResultGateInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.agents.types.request import Start
from acme.om.agents.types.run import RunEnd
from acme.om.base import new_id
from acme.om.context import Role
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.ports import WorkProductAbsentImpl
from acme.om.exceptions import NotAuthorized, NotFound, Unavailable
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.steps.types.header import LoopOutcome, ParkReason
from acme.om.steps.types.step import Step, StepType
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.workspaces.impl.tools import HeldWorkspaces
from acme.om.workspaces.impl.work_product import WorkProductWorkspacesImpl
from acme.om.workspaces.rules import SNAPSHOT_PREFIX, session_branch
from acme.om.workspaces.types.egress import (
    READ_ONLY,
    EgressAllowlist,
    EgressMethod,
    EgressRequest,
    EgressRule,
)
from acme.om.workspaces.types.source import PullRequestFate, RepositoryWrite, WriteKind


def kind(name: str, mode: IsolationMode, egress: EgressMode = EgressMode.OPEN) -> AgentKind:
    spec = IsolationSpec(mode=mode, egress=EgressPolicy(mode=egress))
    return ASSISTANT.model_copy(update={"name": name, "isolation": spec})


TWINNED = kind("twinned", IsolationMode.TWIN)
CONTAINED = kind("contained", IsolationMode.CONTAINER, EgressMode.NONE)

SOURCE = EgressRule(destination="git.example.com", methods=(EgressMethod.GET, EgressMethod.POST))
MIRROR = EgressRule(destination="*.mirror.example.com", methods=READ_ONLY)


def gate(storage: StorageInterface) -> ResultGateInterface:
    """The evidence's gate, as a deployed root takes it: outside `local`, a
    root refuses the null one."""
    return ResultGateEvidenceImpl(
        storage.get_evidence_storage(),
        WorkProductAbsentImpl(),
        SessionProjectsBoundImpl(storage.get_project_storage()),
    )


def loop_of(tmp_path: Path, *kinds: AgentKind, **roots: Any) -> Loop:
    return loop_over(tmp_path, kinds=kinds or (TWINNED,), **roots)


def provider(loop: Loop) -> WorkspaceTwinImpl:
    workspaces = loop.infra.get_workspaces()
    assert isinstance(workspaces, WorkspaceTwinImpl)
    return workspaces


def of_type(steps: list[Step], step_type: StepType) -> list[Step]:
    return [step for step in steps if step.type is step_type]


async def one_loop(loop: Loop, session_id: Any, text: str = "Answer it.") -> Any:
    await loop.say(session_id, text)
    loop.anthropic.add(reply(said("Done.")))
    return await loop.loops.run(loop.owner, session_id)


# Check 1: a host that cannot give a session's pinned isolation refuses its
# workspace before the first model call, and the loop parks on `resource`.


async def test_a_host_that_cannot_give_the_pinned_isolation_parks_the_loop_on_the_resource(
    tmp_path: Path,
) -> None:
    # A host of the platform's cloud: the twin's level is local's alone, so
    # this host refuses it before its provider, which would take it, is
    # reached.
    storage = StorageMemoryImpl()
    loop = loop_of(tmp_path, storage=storage, environment="production", result_gate=gate(storage))
    session_id = await loop.start("twinned")
    pinned = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert pinned.level is IsolationMode.TWIN, "pinned when the session was created"

    run = await one_loop(loop, session_id)

    assert run.end is RunEnd.PARKED and run.park is not None
    assert run.park.reason is ParkReason.RESOURCE and run.park.unlock == "workspace"
    assert run.park.retry_at is not None and run.park.retry_at > loop.clock()
    assert loop.anthropic.calls == [], "refused before the first model call"
    assert provider(loop).live == set(), "no weaker place, and no place at all, was made"
    steps = await loop.history(session_id)
    assert [step.type for step in steps] == [StepType.MESSAGE, StepType.PARKED]

    # At its retry time it asks again, and a host that still cannot give it
    # parks it again: it waits, and never runs on less.
    loop.clock.now = run.park.retry_at
    await loop.managers.agent_sessions.wake_session(loop.owner, session_id, run.park)
    again = await loop.loops.run(loop.owner, session_id)
    assert again.park is not None and again.park.reason is ParkReason.RESOURCE
    assert loop.anthropic.calls == []


async def test_a_prepare_is_held_to_the_pin_whatever_a_loop_asks(tmp_path: Path) -> None:
    loop = loop_of(tmp_path, CONTAINED)
    session_id = await loop.start("contained")
    weaker = IsolationSpec(mode=IsolationMode.TWIN, egress=EgressPolicy(mode=EgressMode.OPEN))

    with pytest.raises(IsolationRefused):
        await loop.managers.tools.prepare_workspace(loop.owner, session_id, weaker)

    assert provider(loop).live == set(), "the twin was asked for the container, and refused it"
    pinned = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert (pinned.level, pinned.egress) == (IsolationMode.CONTAINER, EgressMode.NONE)


async def test_a_session_never_pinned_is_pinned_at_its_first_prepare_and_held_to_it(
    tmp_path: Path,
) -> None:
    loop = loop_of(tmp_path)
    session_id = new_id()
    with pytest.raises(NotFound):
        await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    asked = TWINNED.isolation

    workspace = await loop.managers.tools.prepare_workspace(loop.owner, session_id, asked)
    await loop.managers.tools.release_workspace(loop.owner, workspace)

    pinned = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert pinned.level is IsolationMode.TWIN
    asked_again = CONTAINED.isolation
    again = await loop.managers.tools.prepare_workspace(loop.owner, session_id, asked_again)
    assert again.spec.mode is IsolationMode.TWIN, "the pin, not what a later loop asks"


# Check 2: before release, uncommitted work is committed to a snapshot ref
# and pushed, the next loop is told, and a vanished branch with no known
# reason fails loudly.


async def test_the_work_a_loop_left_is_pushed_before_release_and_the_next_loop_is_told(
    tmp_path: Path,
) -> None:
    git = GitTwin()
    loop = loop_of(tmp_path, workspace_projects=ProjectsTwin(), workspace_git=git)
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    assert (await one_loop(loop, session_id)).outcome is LoopOutcome.SUCCEEDED
    assert git.cuts == [branch], "its first loop cut the branch from the default branch"
    assert git.pushed == {}, "a clean checkout keeps nothing"
    git.dirty = True  # the next loop leaves work uncommitted

    second = await one_loop(loop, session_id, "Go on.")

    assert second.outcome is LoopOutcome.SUCCEEDED
    assert git.cuts == [branch], "the branch the checkout holds is kept"
    ((ref, commit),) = git.pushed.items()
    assert ref.startswith(f"{SNAPSHOT_PREFIX}/{branch}/"), "beside the branch, never on it"
    held = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert held.snapshot_ref == ref and held.notice is not None and commit in held.notice
    assert provider(loop).live == set(), "kept, then let go"

    git.dirty = False
    third = await one_loop(loop, session_id, "And now?")

    assert third.outcome is LoopOutcome.SUCCEEDED
    steps = await loop.history(session_id)
    (told,) = of_type(steps, StepType.ENVIRONMENT_CHANGED)
    assert ref in told.as_text() and commit in told.as_text()
    requests = of_type(steps, StepType.MODEL_REQUEST)
    assert requests[1].seq < told.seq < requests[2].seq, "told before the next loop's call"
    assert told.id in requests[2].refs, "the call delivered it"
    held = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert held.notice is None, "told once"


async def test_a_workspace_whose_work_is_not_pushed_is_not_let_go(tmp_path: Path) -> None:
    git = GitTwin()
    loop = loop_of(tmp_path, workspace_projects=ProjectsTwin(), workspace_git=git)
    session_id = await loop.start("twinned")
    assert (await one_loop(loop, session_id)).outcome is LoopOutcome.SUCCEEDED
    git.dirty, git.refuses_push = True, True

    run = await one_loop(loop, session_id, "Go on.")

    assert run.outcome is LoopOutcome.SUCCEEDED
    assert session_id in provider(loop).live, "the instance, and the work in it, stay"
    held = await loop.managers.workspaces.get_workspace(loop.owner, session_id)
    assert held.snapshot_ref is None and held.notice is None


async def test_a_dirty_checkout_is_kept_before_it_is_cut_or_nothing_is_cut(
    tmp_path: Path,
) -> None:
    git = GitTwin()
    pull_requests = PullRequestsTwin()
    loop = loop_of(
        tmp_path,
        workspace_projects=ProjectsTwin(),
        workspace_git=git,
        pull_requests=pull_requests,
    )
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    git.remote.add(branch)
    assert (await one_loop(loop, session_id)).outcome is LoopOutcome.SUCCEEDED
    # Its pull request merged and its branch went, while the checkout still
    # holds work a release could not push.
    git.remote.discard(branch)
    pull_requests.fates[branch] = PullRequestFate.MERGED
    git.dirty, git.refuses_push = True, True
    git.calls.clear()
    await loop.say(session_id, "Next change.")
    loop.anthropic.add(reply(said("Never asked.")))

    with pytest.raises(Unavailable):
        await loop.loops.run(loop.owner, session_id)

    assert git.cuts == [] and git.calls == ["snapshot"], "nothing was cut over the work"
    git.refuses_push = False
    git.calls.clear()

    rebuilt = await loop.loops.run(loop.owner, session_id)

    assert rebuilt.outcome is LoopOutcome.SUCCEEDED
    assert git.calls[:2] == ["snapshot", "cut"], "kept first, then cut"
    ((ref, commit),) = git.pushed.items()
    (told,) = of_type(await loop.history(session_id), StepType.ENVIRONMENT_CHANGED)
    assert ref in told.as_text() and commit in told.as_text() and "merged" in told.as_text()


async def test_a_branch_that_moved_here_and_on_its_repository_ends_the_loop_loudly(
    tmp_path: Path,
) -> None:
    git = GitTwin()
    loop = loop_of(tmp_path, workspace_projects=ProjectsTwin(), workspace_git=git)
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    git.remote.add(branch)
    git.local.add(branch)
    git.diverged = True

    run = await one_loop(loop, session_id)

    assert run.outcome is LoopOutcome.ERRORED and loop.anthropic.calls == []
    assert git.cuts == [], "nothing merged or cut"


async def test_a_vanished_branch_with_no_known_reason_ends_the_loop_loudly(
    tmp_path: Path,
) -> None:
    git = GitTwin()
    loop = loop_of(tmp_path, workspace_projects=ProjectsTwin(), workspace_git=git)
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    git.remote.add(branch)
    git.local.add(branch)
    assert (await one_loop(loop, session_id)).outcome is LoopOutcome.SUCCEEDED
    assert (await loop.managers.workspaces.get_workspace(loop.owner, session_id)).branch_seen
    git.remote.discard(branch)
    calls = len(loop.anthropic.calls)

    lost = await one_loop(loop, session_id, "Go on.")

    assert lost.outcome is LoopOutcome.ERRORED
    assert len(loop.anthropic.calls) == calls, "it failed before the first model call"
    assert git.cuts == [], "nothing restarted from the default branch"
    assert provider(loop).live == set()


async def test_a_branch_gone_after_its_pull_request_merged_is_rebuilt_and_the_loop_told(
    tmp_path: Path,
) -> None:
    git = GitTwin()
    pull_requests = PullRequestsTwin()
    loop = loop_of(
        tmp_path,
        workspace_projects=ProjectsTwin(),
        workspace_git=git,
        pull_requests=pull_requests,
    )
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    git.remote.add(branch)
    assert (await one_loop(loop, session_id)).outcome is LoopOutcome.SUCCEEDED
    git.remote.discard(branch)
    pull_requests.fates[branch] = PullRequestFate.MERGED

    rebuilt = await one_loop(loop, session_id, "Next change.")

    assert rebuilt.outcome is LoopOutcome.SUCCEEDED
    assert git.cuts == [branch]
    (told,) = of_type(await loop.history(session_id), StepType.ENVIRONMENT_CHANGED)
    assert "merged" in told.as_text() and branch in told.as_text()


# Check 3: a session's egress is its project's allowlist, pinned, and what
# is outside it, or inside the platform, is refused.


def ask(destination: str, address: str, method: EgressMethod | None) -> EgressRequest:
    return EgressRequest(
        destination=destination, address=ip_address(address), port=443, method=method
    )


async def test_a_sessions_egress_is_its_projects_allowlist_as_pinned(tmp_path: Path) -> None:
    projects = ProjectsTwin()
    loop = loop_of(tmp_path, workspace_projects=projects)
    workspaces = loop.managers.workspaces
    listed = EgressAllowlist(
        id=new_id(),
        created_at=loop.clock(),
        updated_at=loop.clock(),
        created_by=loop.owner.user_id,
        updated_by=loop.owner.user_id,
        project_id=projects.project_id,
        rules=(SOURCE, MIRROR),
    )
    written = await workspaces.write_allowlist(loop.owner, listed)
    session_id = await loop.start("twinned")

    async def allowed(request: EgressRequest, of: Any = session_id) -> bool:
        return (await workspaces.egress(loop.owner, of, request)).allowed

    assert await allowed(ask("git.example.com", "93.184.215.14", EgressMethod.POST))
    assert await allowed(ask("pypi.mirror.example.com", "93.184.215.15", EgressMethod.GET))
    assert not await allowed(ask("git.example.com", "93.184.215.14", EgressMethod.DELETE))
    assert not await allowed(ask("pypi.mirror.example.com", "93.184.215.15", EgressMethod.PUT))
    assert not await allowed(ask("paste.example.net", "93.184.215.16", EgressMethod.POST))
    assert not await allowed(ask("git.example.com", "169.254.169.254", EgressMethod.GET))
    assert not await allowed(ask("git.example.com", "10.0.3.4", EgressMethod.GET))

    # Open egress is a choice recorded with its reason and who made it; it
    # reaches the sessions created after it, and the one before keeps its pin.
    opened = written.model_copy(
        update={"rules": (), "open": True, "reason": "the build fetches from anywhere"}
    )
    recorded = await workspaces.write_allowlist(loop.owner, opened)
    assert (recorded.version, recorded.updated_by) == (2, loop.owner.user_id)
    later = await loop.start("twinned")

    assert not await allowed(ask("paste.example.net", "93.184.215.16", EgressMethod.POST))
    assert await allowed(ask("paste.example.net", "93.184.215.16", EgressMethod.POST), later)
    assert not await allowed(ask("metadata.google.internal", "93.184.215.17", None), later)
    assert not await allowed(ask("any.example.org", "169.254.169.254", None), later)
    assert not await allowed(ask("any.example.org", "192.168.1.20", None), later)


async def test_only_one_who_manages_the_tenant_writes_an_allowlist(tmp_path: Path) -> None:
    loop = loop_of(tmp_path)
    member = loop.colleague()
    assert member.role is Role.MEMBER
    listed = EgressAllowlist(
        id=new_id(),
        created_at=loop.clock(),
        updated_at=loop.clock(),
        created_by=member.user_id,
        updated_by=member.user_id,
        project_id=new_id(),
        rules=(SOURCE,),
    )
    with pytest.raises(NotAuthorized):
        await loop.managers.workspaces.write_allowlist(member, listed)


# Check 4: a session's own branch and pull request on its project's bound
# repository are its work product, and every other write acts outward.


async def test_the_sessions_own_branch_and_pull_request_are_work_product_and_all_else_outward(
    tmp_path: Path,
) -> None:
    loop = loop_of(tmp_path, workspace_projects=ProjectsTwin())
    session_id = await loop.start("twinned")
    branch = session_branch(session_id)
    workspaces = loop.managers.workspaces

    async def outward(kind: WriteKind, ref: str, repository: str = REPOSITORY) -> bool:
        write = RepositoryWrite(repository=repository, kind=kind, ref=ref)
        return await workspaces.outward(loop.owner, session_id, write)

    assert not await outward(WriteKind.PUSH, branch)
    assert not await outward(WriteKind.PUSH, f"refs/heads/{branch}")
    assert not await outward(WriteKind.PULL_REQUEST, branch)
    assert await outward(WriteKind.PUSH, "main")
    assert await outward(WriteKind.PUSH, session_branch(new_id()))
    assert await outward(WriteKind.PULL_REQUEST, "release")
    assert await outward(WriteKind.OTHER, branch)
    assert await outward(WriteKind.PUSH, branch, "https://git.example.com/ajax/other.git")

    unbound = loop_of(tmp_path / "unbound", workspace_projects=ProjectsTwin(repository=None))
    unbound_session = await unbound.start("twinned")
    own = RepositoryWrite(
        repository=REPOSITORY, kind=WriteKind.PUSH, ref=session_branch(unbound_session)
    )
    assert await unbound.managers.workspaces.outward(unbound.owner, unbound_session, own)


# What a session delivered, for the evidence: read from the checkout of the
# workspace this host holds, never from what the agent says.


async def test_what_a_session_delivered_is_read_from_the_workspace_this_host_holds(
    tmp_path: Path,
) -> None:
    git = GitTwin(head="c" * 40)
    reader = ReaderTwin(head="c" * 40, changed=("checks/test_guard.py",))
    loop = loop_of(
        tmp_path, workspace_projects=ProjectsTwin(), workspace_git=git, workspace_reader=reader
    )
    assert isinstance(
        loop.managers.evidence._work_product,  # pyright: ignore[reportAttributeAccessIssue]
        WorkProductWorkspacesImpl,
    ), "the root reads the evidence's work product from the workspaces"
    session_id = await loop.start("twinned")
    workspace = await loop.managers.tools.prepare_workspace(
        loop.owner, session_id, TWINNED.isolation
    )
    git.dirty = True  # the loop's work, not yet committed
    held = HeldWorkspaces()
    products = WorkProductWorkspacesImpl(loop.managers.workspaces, held)

    with pytest.raises(Unavailable):
        await products.delivered(loop.owner, session_id)
    held.hold(workspace)
    delivered = await products.delivered(loop.owner, session_id)

    assert delivered is not None and delivered.project == "git.example.com/ajax/app"
    assert (delivered.base, delivered.head, delivered.dirty) == (BASE, "c" * 40, True)
    assert delivered.changed == ("checks/test_guard.py",), "as the repository holds it"
    git.dirty = False
    clean = await products.delivered(loop.owner, session_id)
    assert clean is not None and not clean.dirty, "the checkout holds nothing undelivered"
    git.head = "d" * 40
    ahead = await products.delivered(loop.owner, session_id)
    assert ahead is not None and ahead.dirty, "a commit the repository lacks is not delivered"

    unbound = loop_of(tmp_path / "unbound", workspace_projects=ProjectsTwin(repository=None))
    other = await unbound.start("twinned")
    loose = await unbound.managers.tools.prepare_workspace(unbound.owner, other, TWINNED.isolation)
    with pytest.raises(Unavailable):
        await unbound.managers.workspaces.delivery(unbound.owner, loose)


# A session's project and its repository are the projects' rows.


async def test_a_session_started_in_a_project_works_on_the_projects_repository(
    tmp_path: Path,
) -> None:
    loop = loop_of(tmp_path)
    project = await loop.managers.projects.create_project(loop.owner, make_project("octo/reports"))
    listed = EgressAllowlist(
        id=new_id(),
        created_at=loop.clock(),
        updated_at=loop.clock(),
        created_by=loop.owner.user_id,
        updated_by=loop.owner.user_id,
        project_id=project.id,
        rules=(SOURCE,),
    )
    await loop.managers.workspaces.write_allowlist(loop.owner, listed)

    session = await loop.managers.projects.start_session(
        loop.owner, project.id, Start(id=new_id(), kind="twinned", title="a report")
    )

    pinned = await loop.managers.workspaces.get_workspace(loop.owner, session.id)
    assert (pinned.project_id, pinned.rules) == (project.id, (SOURCE,)), "its project's allowlist"
    branch = session_branch(session.id)
    own = RepositoryWrite(
        repository="https://github.com/octo/reports.git", kind=WriteKind.PUSH, ref=branch
    )
    elsewhere = own.model_copy(update={"repository": "https://github.com/octo/other.git"})
    workspaces = loop.managers.workspaces
    assert not await workspaces.outward(loop.owner, session.id, own), "the project's repository"
    assert await workspaces.outward(loop.owner, session.id, elsewhere)
