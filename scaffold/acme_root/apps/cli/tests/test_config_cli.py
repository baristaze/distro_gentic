"""A tenant's configuration from the terminal, against the whole API
in-process: a project created on its repository and listed, its fetch
credential given and never printed, and an automation created from a file
and listed. A member's project is refused by the API; a malformed
repository or file is usage."""

import json
from pathlib import Path

from cli_support import BOB, Stack

PASSWORD = "ghp_never-printed-0123456789"


def created_project(stack: Stack) -> str:
    result = stack.acme("project", "create", "the weekly reports", "github.com/Octo/Reports")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("created ")
    assert result.output.endswith(" on github.com/octo/reports\n")
    return result.output.split()[1]


def automation_file(tmp_path: Path, project_id: str) -> Path:
    path = tmp_path / "triage.json"
    path.write_text(
        json.dumps(
            {
                "name": "triage a failed build",
                "trigger": {"kind": "event", "effects": ["ci_failed"]},
                "action": {
                    "kind": "start_session",
                    "brief": "Find why the build failed.",
                    "agent_kind": "assistant",
                    "title": "a failed build",
                    "project_id": project_id,
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


def test_a_project_is_created_listed_and_given_a_credential(stack: Stack) -> None:
    project_id = created_project(stack)
    listed = stack.acme("project", "list")
    assert listed.exit_code == 0, listed.output
    assert project_id in listed.output and "the weekly reports" in listed.output
    given = stack.acme(
        "project",
        "credential",
        project_id,
        "--username",
        "reader",
        env={"ACME_FETCH_PASSWORD": PASSWORD},
    )
    assert given.exit_code == 0, given.output
    assert given.output == f"fetch credential 1 of {project_id} is set\n"
    shown = stack.acme("project", "list", "--json")
    assert PASSWORD not in given.output + shown.output


def test_an_automation_is_created_from_a_file_and_listed(stack: Stack, tmp_path: Path) -> None:
    project_id = created_project(stack)
    made = stack.acme("automation", "create", str(automation_file(tmp_path, project_id)))
    assert made.exit_code == 0, made.output
    assert made.output.startswith("created ")
    assert made.output.endswith(" (triage a failed build), runs as creator\n")
    automation_id = made.output.split()[1]
    listed = stack.acme("automation", "list", "--json")
    assert [a["id"] for a in json.loads(listed.output)] == [automation_id]


def test_a_member_creates_no_project_and_a_malformed_input_is_usage(
    stack: Stack, tmp_path: Path
) -> None:
    member = stack.acme(
        "project",
        "create",
        "theirs",
        "github.com/octo/ledger",
        token=stack.session_token(BOB["email"]),
    )
    assert member.exit_code == 1
    assert "not_authorized" in member.output
    assert stack.acme("project", "create", "no path", "github.com").exit_code == 2
    broken = tmp_path / "broken.json"
    broken.write_text('{"name": "no trigger"}')
    assert stack.acme("automation", "create", str(broken)).exit_code == 2
    assert "theirs" not in stack.acme("project", "list").output
