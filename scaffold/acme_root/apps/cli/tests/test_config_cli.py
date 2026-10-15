"""A tenant's configuration from the terminal, against the whole API
in-process: an agent project created on its repository and listed, its fetch
credential given and never printed, and an agent automation created from a file
and listed. A member's agent project is refused by the API; a malformed
repository or file is usage."""

import json
from pathlib import Path

from cli_support import BOB, Stack

PASSWORD = "ghp_never-printed-0123456789"


def created_agent_project(stack: Stack) -> str:
    result = stack.acme("agent-project", "create", "the weekly reports", "github.com/Octo/Reports")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("created ")
    assert result.output.endswith(" on github.com/octo/reports\n")
    return result.output.split()[1]


def agent_automation_file(tmp_path: Path, agent_project_id: str) -> Path:
    path = tmp_path / "triage.json"
    path.write_text(
        json.dumps(
            {
                "name": "triage a failed build",
                "trigger": {"kind": "event", "effects": ["ci_failed"]},
                "action": {
                    "kind": "start_agent_session",
                    "brief": "Find why the build failed.",
                    "agent_kind": "assistant",
                    "title": "a failed build",
                    "agent_project_id": agent_project_id,
                },
                "limits": {
                    "cost_cap_micros": 5_000_000,
                    "run_cap_micros": 1_000_000,
                    "rate": 10,
                    "concurrency": 2,
                },
            }
        )
    )
    return path


def test_an_agent_project_is_created_listed_and_given_a_credential(stack: Stack) -> None:
    agent_project_id = created_agent_project(stack)
    listed = stack.acme("agent-project", "list")
    assert listed.exit_code == 0, listed.output
    assert agent_project_id in listed.output and "the weekly reports" in listed.output
    given = stack.acme(
        "agent-project",
        "credential",
        agent_project_id,
        "--username",
        "reader",
        env={"ACME_FETCH_PASSWORD": PASSWORD},
    )
    assert given.exit_code == 0, given.output
    assert given.output == f"fetch credential 1 of {agent_project_id} is set\n"
    shown = stack.acme("agent-project", "list", "--json")
    assert PASSWORD not in given.output + shown.output


def test_an_agent_automation_is_created_from_a_file_and_listed(
    stack: Stack, tmp_path: Path
) -> None:
    agent_project_id = created_agent_project(stack)
    made = stack.acme(
        "agent-automation", "create", str(agent_automation_file(tmp_path, agent_project_id))
    )
    assert made.exit_code == 0, made.output
    assert made.output.startswith("created ")
    assert made.output.endswith(" (triage a failed build), runs as creator\n")
    agent_automation_id = made.output.split()[1]
    listed = stack.acme("agent-automation", "list", "--json")
    assert [a["id"] for a in json.loads(listed.output)] == [agent_automation_id]


def test_a_member_creates_no_agent_project_and_a_malformed_input_is_usage(
    stack: Stack, tmp_path: Path
) -> None:
    member = stack.acme(
        "agent-project",
        "create",
        "theirs",
        "github.com/octo/ledger",
        token=stack.auth_session_token(BOB["email"]),
    )
    assert member.exit_code == 1
    assert "not_authorized" in member.output
    assert stack.acme("agent-project", "create", "no path", "github.com").exit_code == 2
    broken = tmp_path / "broken.json"
    broken.write_text('{"name": "no trigger"}')
    assert stack.acme("agent-automation", "create", str(broken)).exit_code == 2
    assert "theirs" not in stack.acme("agent-project", "list").output
