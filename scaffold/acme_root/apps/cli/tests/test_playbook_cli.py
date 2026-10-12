"""A playbook from the terminal, against the whole API in-process: invoked
into a session, whose brief arrives as the caller's message, and pinned to
a kind as its manual, listed, and taken away. A name with no version is
refused with the API's reason."""

from api_support import OWNER, PROJECT_ID
from cli_support import Stack

PLAYBOOK = {
    "name": "answer-from-the-ledger",
    "description": "How an assistant answers from the ledger.",
    "body": "1. Quote the ledger's line for each total you give.",
    "gates": [{"tool": "lookup", "decision": "deny"}],
}


def published(stack: Stack) -> None:
    headers = {
        "Authorization": f"Bearer {stack.session_token(OWNER['email'])}",
        "Idempotency-Key": "publish-answer-from-the-ledger",
    }
    made = stack.tc.post("/v1/playbooks", headers=headers, json=PLAYBOOK)
    assert made.status_code == 201, made.text


def started(stack: Stack) -> str:
    result = stack.acme("session", "start", "assistant", "the ledger", "--project", PROJECT_ID)
    assert result.exit_code == 0, result.output
    return result.output.split()[1]


def test_a_playbook_is_invoked_into_a_session_and_its_brief_is_the_callers_message(
    stack: Stack,
) -> None:
    published(stack)
    session_id = started(stack)
    invoked = stack.acme("playbook", "invoke", session_id, PLAYBOOK["name"])
    assert invoked.exit_code == 0, invoked.output
    assert invoked.output == f"invoked {PLAYBOOK['name']} 1 into {session_id}\n"
    steps = stack.acme("session", "steps", session_id)
    assert steps.exit_code == 0, steps.output
    assert "message" in steps.output and "name: answer-from-the-ledger" in steps.output

    refused = stack.acme("playbook", "invoke", session_id, "no-such-playbook")
    assert refused.exit_code != 0
    assert "not found" in refused.output


def test_a_playbook_is_pinned_to_a_kind_listed_and_taken_away(stack: Stack) -> None:
    published(stack)
    pinned = stack.acme("playbook", "pin", "assistant", PLAYBOOK["name"])
    assert pinned.exit_code == 0, pinned.output
    assert pinned.output == f"pinned assistant  {PLAYBOOK['name']} 1  every project\n"
    narrowed = stack.acme("playbook", "pin", "assistant", PLAYBOOK["name"], "--project", PROJECT_ID)
    assert narrowed.exit_code == 0, narrowed.output
    listed = stack.acme("playbook", "pins")
    assert listed.output.splitlines() == [
        f"assistant  {PLAYBOOK['name']} 1  every project",
        f"assistant  {PLAYBOOK['name']} 1  project {PROJECT_ID}",
    ]
    unpinned = stack.acme("playbook", "unpin", "assistant")
    assert unpinned.exit_code == 0, unpinned.output
    assert stack.acme("playbook", "pins").output.splitlines() == [
        f"assistant  {PLAYBOOK['name']} 1  project {PROJECT_ID}"
    ]
