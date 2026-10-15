"""An agent playbook from the terminal, against the whole API in-process: invoked
into a session, whose brief arrives as the caller's message, and pinned to
a kind as its kind manual, listed, and taken away. A name with no version is
refused with the API's reason."""

from api_support import AGENT_PROJECT_ID, OWNER
from cli_support import Stack

AGENT_PLAYBOOK = {
    "name": "answer-from-the-ledger",
    "description": "How an assistant answers from the ledger.",
    "body": "1. Quote the ledger's line for each total you give.",
    "gates": [{"tool": "lookup", "decision": "deny"}],
}


def published(stack: Stack) -> None:
    headers = {
        "Authorization": f"Bearer {stack.auth_session_token(OWNER['email'])}",
        "Idempotency-Key": "publish-answer-from-the-ledger",
    }
    made = stack.tc.post("/v1/agent-playbooks", headers=headers, json=AGENT_PLAYBOOK)
    assert made.status_code == 201, made.text


def started(stack: Stack) -> str:
    result = stack.acme(
        "agent-session", "start", "assistant", "the ledger", "--agent-project", AGENT_PROJECT_ID
    )
    assert result.exit_code == 0, result.output
    return result.output.split()[1]


def test_a_agent_playbook_is_invoked_into_a_session_and_its_brief_is_the_callers_message(
    stack: Stack,
) -> None:
    published(stack)
    agent_session_id = started(stack)
    invoked = stack.acme("agent-playbook", "invoke", agent_session_id, AGENT_PLAYBOOK["name"])
    assert invoked.exit_code == 0, invoked.output
    assert invoked.output == f"invoked {AGENT_PLAYBOOK['name']} 1 into {agent_session_id}\n"
    steps = stack.acme("agent-session", "steps", agent_session_id)
    assert steps.exit_code == 0, steps.output
    assert "message" in steps.output and "name: answer-from-the-ledger" in steps.output

    refused = stack.acme("agent-playbook", "invoke", agent_session_id, "no-such-agent-playbook")
    assert refused.exit_code != 0
    assert "not found" in refused.output


def test_a_agent_playbook_is_pinned_to_a_kind_listed_and_taken_away(stack: Stack) -> None:
    published(stack)
    pinned = stack.acme("agent-playbook", "pin", "assistant", AGENT_PLAYBOOK["name"])
    assert pinned.exit_code == 0, pinned.output
    assert pinned.output == f"pinned assistant  {AGENT_PLAYBOOK['name']} 1  every agent project\n"
    narrowed = stack.acme(
        "agent-playbook",
        "pin",
        "assistant",
        AGENT_PLAYBOOK["name"],
        "--agent-project",
        AGENT_PROJECT_ID,
    )
    assert narrowed.exit_code == 0, narrowed.output
    listed = stack.acme("agent-playbook", "pins")
    assert listed.output.splitlines() == [
        f"assistant  {AGENT_PLAYBOOK['name']} 1  every agent project",
        f"assistant  {AGENT_PLAYBOOK['name']} 1  agent project {AGENT_PROJECT_ID}",
    ]
    unpinned = stack.acme("agent-playbook", "unpin", "assistant")
    assert unpinned.exit_code == 0, unpinned.output
    assert stack.acme("agent-playbook", "pins").output.splitlines() == [
        f"assistant  {AGENT_PLAYBOOK['name']} 1  agent project {AGENT_PROJECT_ID}"
    ]
