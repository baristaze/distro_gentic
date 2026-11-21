"""A session from the terminal, against the whole API in-process: started,
spoken to, steered, and read one step a line; `steps --follow`, which
reads until the loop stops and exits by how it ended; and `attach`, which
serves a person's own local session from this machine and follows any
other. No runner works
behind the API here, so a case writes the loop's steps itself, the way a
run writes them."""

import json
from uuid import UUID

import pytest
from api_support import AGENT_PROJECT_ID, OWNER, run, seed_request
from cli_support import Stack

from acme.apps.cli import main
from acme.om.agent_steps.types.header import LoopOutcome, Park, ParkReason
from acme.om.agents.loop_rules import ended_step
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.hosts.types.host import Advertisement, Enrollment, IsolationMode

from contracts.agent_step_storage import make_request, make_response


def owner_context(stack: Stack) -> TenantContext:
    tenancy = stack.container.managers.tenancy
    return run(tenancy.authenticate(seed_request(), stack.auth_session_token(OWNER["email"])))


def started(stack: Stack) -> str:
    result = stack.acme(
        "agent-session",
        "start",
        "assistant",
        "the dropped object",
        "--agent-project",
        AGENT_PROJECT_ID,
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("started ") and result.output.endswith(" on assistant 1\n")
    return result.output.split()[1]


APPROVAL = Park(reason=ParkReason.PERSON, unlock="approval")


def a_loop_ran(
    stack: Stack,
    agent_session_id: str,
    outcome: LoopOutcome | None,
    *,
    park: Park = APPROVAL,
    cause: str | None = None,
) -> None:
    """A run's steps: its request delivered the message and was answered,
    then the loop ended with `outcome` and `cause`, or parked on `park` with
    None."""
    ctx = owner_context(stack)
    sid = UUID(agent_session_id)
    managers = stack.container.managers

    async def write() -> None:
        epoch = await managers.agent_steps.begin_run(ctx, sid)
        (message,) = (await managers.agent_steps.get_agent_steps(ctx, sid, 0, 10)).items
        request = make_request(sid, message.loop_id, (message.id,))
        response = make_response(sid, message.loop_id, request.id)
        await managers.agent_steps.append_agent_steps(ctx, sid, epoch, [request, response])
        if outcome is None:
            await managers.agent_sessions.park(ctx, sid, epoch, message.loop_id, park)
            return
        ended = ended_step(new_id(), utcnow(), sid, message.loop_id, outcome, cause=cause)
        await managers.agent_steps.append_agent_steps(ctx, sid, epoch, [ended])
        await managers.agent_sessions.project_status(ctx, sid)

    run(write())


def test_a_session_is_started_spoken_to_steered_and_read(stack: Stack) -> None:
    agent_session_id = started(stack)

    said = stack.acme("agent-session", "say", agent_session_id, "Why does the export time out?")
    paused = stack.acme("agent-session", "control", agent_session_id, "pause")
    read = stack.acme("agent-session", "steps", agent_session_id)

    assert said.exit_code == 0 and paused.exit_code == 0, said.output + paused.output
    assert said.output.split() == ["1", "message", "Why", "does", "the", "export", "time", "out?"]
    assert paused.output.split() == ["2", "control", "pause"]
    assert read.exit_code == 0, read.output
    assert [line.split()[:2] for line in read.output.splitlines()] == [
        ["1", "message"],
        ["2", "control"],
    ]


def test_a_control_the_loop_does_not_take_is_a_usage_error(stack: Stack) -> None:
    agent_session_id = started(stack)
    refused = stack.acme("agent-session", "control", agent_session_id, "approve")
    assert refused.exit_code == main.EXIT_USAGE, refused.output


def test_following_a_loop_that_succeeded_reads_to_its_end_and_exits_zero(stack: Stack) -> None:
    agent_session_id = started(stack)
    stack.acme("agent-session", "say", agent_session_id, "Investigate the drop.")
    a_loop_ran(stack, agent_session_id, LoopOutcome.SUCCEEDED)

    followed = stack.acme("agent-session", "steps", agent_session_id, "--follow")

    assert followed.exit_code == 0, followed.output
    lines = followed.output.splitlines()
    assert [line.split()[1] for line in lines] == [
        "message",
        "model_request",
        "model_response",
        "loop_ended",
    ]
    assert lines[-1].split()[2] == "succeeded"


def test_following_a_loop_that_parked_exits_by_it(stack: Stack) -> None:
    agent_session_id = started(stack)
    stack.acme("agent-session", "say", agent_session_id, "Push the fix.")
    a_loop_ran(stack, agent_session_id, None)

    followed = stack.acme("agent-session", "steps", agent_session_id, "--follow", "--after", "3")

    assert followed.exit_code == main.EXIT_UNSUCCESSFUL, followed.output
    assert followed.output.split() == ["4", "parked", "person,", "until", "approval"]


def test_the_orgs_sessions_are_listed_one_a_line_in_a_status(stack: Stack) -> None:
    first, second = started(stack), started(stack)
    stack.acme("agent-session", "say", second, "Investigate the drop.")

    every = stack.acme("agent-session", "list")
    pending = stack.acme("agent-session", "list", "--status", "pending")

    assert every.exit_code == 0, every.output
    lines = every.output.splitlines()
    assert [line.split()[0] for line in lines] == sorted([first, second], reverse=True)
    assert {tuple(line.split()[1:3]) for line in lines} == {
        ("idle", "assistant"),
        ("pending", "assistant"),
    }
    assert pending.exit_code == 0, pending.output
    assert pending.output.split()[:5] == [second, "pending", "assistant", "the", "dropped"]


def test_a_loops_end_and_its_park_say_their_cause_on_their_line(stack: Stack) -> None:
    ended, parked = started(stack), started(stack)
    for agent_session_id in (ended, parked):
        stack.acme("agent-session", "say", agent_session_id, "Run the tests.")
    failed = "the base's setup command 1, 'pip install acme-tools', exited 2"
    a_loop_ran(stack, ended, LoopOutcome.ERRORED, cause=failed)
    lost = Park(reason=ParkReason.PERSON, unlock="agent_workspace", cause="the snapshot is gone")
    a_loop_ran(stack, parked, None, park=lost)

    end = stack.acme("agent-session", "steps", ended, "--after", "3")
    park = stack.acme("agent-session", "steps", parked, "--after", "3")

    assert end.output.strip().split(maxsplit=2) == ["4", "loop_ended", f"errored: {failed}"]
    assert park.output.strip().split(maxsplit=2) == [
        "4",
        "parked",
        "person, until agent_workspace: the snapshot is gone",
    ]


def served_here(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """This machine's serving, recorded: each key it was handed, and it
    stops at once."""
    keys: list[str] = []

    async def serve_here(api_url: str, key: str) -> None:
        keys.append(key)

    monkeypatch.setattr(main, "serve_here", serve_here)
    return keys


def test_a_local_session_is_served_from_this_machine_its_kind_asking_for_a_workspace(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = served_here(monkeypatch)
    started = stack.acme(
        "agent-session",
        "start",
        "coder",
        "fix the export",
        "--agent-project",
        AGENT_PROJECT_ID,
        "--workspace",
        "local",
    )
    assert started.exit_code == 0, started.output
    agent_session_id = started.output.split()[1]
    assert f"serving session {agent_session_id}'s workspace from this machine" in started.output
    assert len(keys) == 1 and keys[0].startswith("hck_")
    hosts = stack.container.managers.hosts
    placed = run(hosts.placement_of(owner_context(stack), UUID(agent_session_id)))
    assert placed.pool is not None and placed.pool.region == "local" and placed.waiting
    # Attached again, this machine serves it with a key of its own.
    attached = stack.acme("agent-session", "attach", agent_session_id)
    assert attached.exit_code == 0, attached.output
    assert len(keys) == 2 and keys[1] != keys[0]
    # A kind that asks for no workspace has none to serve.
    refused = stack.acme(
        "agent-session",
        "start",
        "assistant",
        "a question",
        "--agent-project",
        AGENT_PROJECT_ID,
        "--workspace",
        "local",
    )
    assert refused.exit_code == main.EXIT_REFUSED
    assert "asks for no workspace" in refused.output and len(keys) == 2


def test_attaching_to_a_session_a_vm_holds_follows_its_steps_and_serves_nothing(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = served_here(monkeypatch)
    started = stack.acme(
        "agent-session",
        "start",
        "coder",
        "on the cloud",
        "--agent-project",
        AGENT_PROJECT_ID,
        "--workspace",
        "cloud",
    )
    assert started.exit_code == 0, started.output
    agent_session_id = started.output.split()[1]
    (start,) = [
        r for r in stack.api.sent if r.method == "POST" and r.url.path == "/v1/agent-sessions"
    ]
    assert json.loads(start.content)["workspace"] == "cloud"
    # The cloud pool made the session its pool of one, and a VM's host
    # holds its workspace.
    ctx = owner_context(stack)
    hosts = stack.container.managers.hosts
    pool = run(hosts.session_pool(ctx, UUID(agent_session_id), "eu-west"))
    vm = Enrollment(
        name="vm-1",
        advertisement=Advertisement(
            os="Linux", shell="/bin/sh", isolation_modes=(IsolationMode.VM,)
        ),
        exec_version=3,
    )
    run(hosts.admit_vm(seed_request(), ctx.org_id, pool.id, ctx.user_id, UUID(int=1), vm))
    stack.acme("agent-session", "say", agent_session_id, "Build it.")
    a_loop_ran(stack, agent_session_id, LoopOutcome.SUCCEEDED)

    attached = stack.acme("agent-session", "attach", agent_session_id)

    assert attached.exit_code == 0, attached.output
    assert "following: " in attached.output and "a VM of the cloud pool holds it" in attached.output
    lines = [line.split() for line in attached.output.splitlines()]
    steps = [words[1] for words in lines if words and words[0].isdigit()]
    assert steps == ["message", "model_request", "model_response", "loop_ended"]
    # Refused as a server: no key reached this machine, and the VM's host is
    # the only one its pool holds.
    assert keys == []
    assert [status.host.name for status in run(hosts.get_hosts(ctx, pool.id))] == ["vm-1"]
