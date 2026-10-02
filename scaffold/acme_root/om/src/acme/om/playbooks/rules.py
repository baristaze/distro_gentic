"""Pure rules of playbooks: a version as an Agent Skills brief, and where
its gates leave a call. Values in, values out.

A call stands at the strictest of what policy decided for it and what the
session's gates ask of it. A gate never allows, so a playbook narrows a
session's policy, whatever it says, and never widens it."""

import json
from collections.abc import Iterable

from acme.om.playbooks.types.playbook import Playbook, PlaybookGate
from acme.om.tools.rules import strictest
from acme.om.tools.types.policy import Decision

GATES_KEY = "acme.gates"
"""The metadata key the gates travel under in the brief: namespaced by the
platform's name, so no other reader of the standard takes it for its own."""

VERSION_KEY = "acme.version"


def gated(gates: Iterable[PlaybookGate], tool: str, authorization_class: str) -> Decision | None:
    """The strictest gate that selects a call, by its tool and its class;
    None when no gate does."""
    found = [
        gate.decision
        for gate in gates
        if (gate.tool is None or gate.tool == tool)
        and (gate.authorization_class is None or gate.authorization_class == authorization_class)
    ]
    return max(found, key=lambda decision: decision.strictness, default=None)


def narrowed(
    decided: Decision, gates: Iterable[PlaybookGate], tool: str, authorization_class: str
) -> Decision:
    """Where a call stands once a session's gates are asked: the strictest of
    what policy decided for it and the strictest gate that selects it."""
    found = gated(gates, tool, authorization_class)
    return decided if found is None else strictest(decided, found)


def skill_md(playbook: Playbook) -> str:
    """The version as a SKILL.md: the standard's frontmatter, its gates and
    its version in the metadata extension, then the body. Every value is a
    JSON string, which YAML reads as a quoted scalar."""
    gates = json.dumps(
        [gate.model_dump(mode="json", exclude_none=True) for gate in playbook.gates],
        separators=(",", ":"),
    )
    return "\n".join(
        (
            "---",
            f"name: {playbook.name}",
            f"description: {json.dumps(playbook.description)}",
            "metadata:",
            f"  {VERSION_KEY}: {json.dumps(str(playbook.version))}",
            f"  {GATES_KEY}: {json.dumps(gates)}",
            "---",
            "",
            playbook.body,
        )
    )
