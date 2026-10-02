"""The text report for a person.

The JSON report and `--list` are the engine's (`acme.agentic_check.report`).
"""

from __future__ import annotations

from acme.agentic_check.runner import Result


def text(result: Result) -> str:
    """One `path:line:col: RULE message` line per finding, then a one-line summary."""
    lines = [f"{f.path}:{f.line}:{f.col}: {f.rule} {f.message}" for f in result.findings]
    rules = f"{len(result.rules_run)} rule(s) over {result.files} Python file(s)"
    accepted = f", {len(result.applied)} accepted by an exception" if result.applied else ""
    if lines:
        return "\n".join([*lines, f"\n{len(lines)} finding(s) from {rules}{accepted}"])
    return f"distro-check ok: {rules}{accepted}"
