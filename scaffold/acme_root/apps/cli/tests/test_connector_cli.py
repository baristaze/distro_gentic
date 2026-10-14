"""A tenant's connectors from the terminal, against the whole API
in-process: a server inside the wall connected by the name its host runs
it by, its tools reviewed from a file of the definitions its host lists,
attached to a kind and detached, and listed. Its listing is its host's, so
the API refuses it; a member connects nothing, and a connector with
neither an address nor a host's server is usage."""

import json
from pathlib import Path

from cli_support import BOB, Stack

from acme.om.tools.rules import definition_hash
from acme.om.tools.types.mcp import McpToolDefinition

SECRET = "tok-never-printed-6b0e2a"

FIND = McpToolDefinition(
    name="find",
    description="Finds a ticket.",
    input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
)


def connected(stack: Stack) -> str:
    made = stack.acme(
        "connector", "connect", "tracker", "Read the team's tickets.", "--host-server", "tracker"
    )
    assert made.exit_code == 0, made.output
    assert made.output.startswith("connected ") and made.output.endswith(" (tracker)\n")
    return made.output.split()[1]


def review_file(tmp_path: Path) -> Path:
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "server_tool": "find",
                        "definition_hash": definition_hash(FIND),
                        "authorization_class": "read",
                        "effect": "read_only",
                    }
                ],
                "definitions": [FIND.model_dump(mode="json")],
            }
        )
    )
    return path


def test_a_server_inside_the_wall_is_connected_reviewed_attached_and_detached(
    stack: Stack, tmp_path: Path
) -> None:
    connector_id = connected(stack)
    reviewed = stack.acme("connector", "review", connector_id, str(review_file(tmp_path)))
    assert reviewed.exit_code == 0, reviewed.output
    assert reviewed.output == "review 1 of tracker: tracker__find\n"
    attached = stack.acme("connector", "attach", connector_id, "assistant")
    assert attached.exit_code == 0, attached.output
    shown = json.loads(stack.acme("connector", "list", "--json").output)
    assert [(c["id"], c["attachments"]) for c in shown] == [
        (connector_id, [{"kind": "assistant", "agent_project_id": None, "deferred": True}])
    ]
    listed = stack.acme("connector", "list")
    assert listed.output == f"{connector_id}  tracker  host:tracker  review 1, 1 tools\n"
    detached = stack.acme("connector", "detach", connector_id, "assistant")
    assert detached.exit_code == 0 and detached.output == "tracker is detached from assistant\n"
    listing = stack.acme("connector", "listing", connector_id)
    assert listing.exit_code == 1, "a host's server is listed on its host"
    assert "conflict" in listing.output
    held = stack.acme(
        "connector", "credential", connector_id, env={"ACME_CONNECTOR_CREDENTIAL": SECRET}
    )
    assert held.exit_code == 1, "its credential stays on its host"
    assert "validation_failed" in held.output and SECRET not in held.output


def test_a_member_connects_nothing_and_a_connector_without_a_place_is_usage(
    stack: Stack,
) -> None:
    member = stack.acme(
        "connector",
        "connect",
        "tracker",
        "Read the team's tickets.",
        "--host-server",
        "tracker",
        token=stack.session_token(BOB["email"]),
    )
    assert member.exit_code == 1 and "not_authorized" in member.output
    assert stack.acme("connector", "connect", "tracker", "Read tickets.").exit_code == 2
    assert stack.acme("connector", "list").output == ""
