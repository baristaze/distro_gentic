"""The scene: the words of the demo, in plain data.

It holds what the person says, the repository the software engineer works
on, and every turn the scripted provider answers with, in the order the
runner asks for them. The runner runs one loop at a time, so the turns go
in the order the loops are claimed:

1. The lead, the software engineer, takes a baseline, starts four analysis
   sub-agents in one answer, and waits on them.
2. Each sub-agent runs in the order it was started. The first reads the
   parser and reports. The second searches for the parser's callers and
   asks its person. The third reads the README and starts a sub-agent of
   its own for the test, then waits on it. The fourth reads the invoice
   and reports.
3. Woken by those reports, the lead says what it knows and waits again.
   The third's own sub-agent reads the test and reports to it; the third,
   woken, reports to the lead, which waits on the one that needs its
   person.
4. The person answers in the second sub-agent's chat. It reports, and the
   lead, woken, writes the roll-up, fixes the parser, commits, opens a
   pull request, validates it, and submits its result. The commit and the
   validation each wait for the person's approval.

Nothing here is written through the platform: the script is a file the
runner reads, and the repository is a bare one on disk, where the runner
clones it from.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

PROMPT = "Read every date in the app day first"
"""What the person asks the lead, on Home."""

LEAD = "Software engineer"
"""The agent the person picks for it."""

ANSWER = "Yes, every row writes the day first."
"""What the person answers the sub-agent that asks."""

MODEL = "claude-sonnet-5-5"

PARSER = (
    "from datetime import date\n"
    "\n"
    "\n"
    "def parse(text):\n"
    '    """A date written day first, as 05/10/2026."""\n'
    '    month, day, year = text.split("/")\n'
    "    return date(int(year), int(month), int(day))\n"
)
WRONG = '    month, day, year = text.split("/")\n'
RIGHT = '    day, month, year = text.split("/")\n'

REPOSITORY = {
    "README.md": (
        "# Ledger\n\nReads the rows of a bank's statements. Every date is written day first: 05/10/2026 is 5 October 2026.\n"
    ),
    "src/dates.py": PARSER,
    "src/invoice.py": (
        'from dates import parse\n\n\ndef due(row):\n    """The day an invoice falls due."""\n    return parse(row["due"])\n'
    ),
    "src/report.py": (
        "from dates import parse\n"
        "\n"
        "\n"
        "def line(row):\n"
        '    """One line of the monthly report."""\n'
        '    when = parse(row["date"])\n'
        "    return f\"{when:%d %B %Y}  {row['amount']}\"\n"
    ),
    "tests/test_dates.py": (
        "import sys\n"
        "\n"
        'sys.path.insert(0, "src")\n'
        "from dates import parse  # noqa: E402\n"
        "\n"
        "\n"
        "def test_day_first():\n"
        '    assert parse("05/10/2026").month == 10, "the month is the second part"\n'
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    test_day_first()\n"
        '    print("1 passed")\n'
    ),
    # A host workspace is its command's home, where macOS's Python keeps its
    # caches too: a validation finds the tree clean.
    ".gitignore": "__pycache__/\n/Library/Caches/\n",
}
"""The repository the lead's agent project binds: a parser that takes the
month first, though everything around it writes the day first."""

# The sub-agents, in the order the lead starts them: each title, as the card
# and the left bar show it, and its objective.
PARSE = "Read how parse takes a date"
CALLERS = "Find every caller of parse"
AGREE = "Check the README and the test agree"
INVOICE = "Read how an invoice falls due"
TEST = "Read what the date test expects"
"""The third sub-agent's own sub-agent."""

CHILDREN = (
    (PARSE, "Read parse in src/dates.py and say in which order it takes the parts of a date."),
    (CALLERS, "Find every caller of parse and say how each one writes a date."),
    (AGREE, "Read the README and tests/test_dates.py, and say whether they write a date the same way."),
    (INVOICE, "Read src/invoice.py and say how it takes the day an invoice falls due."),
)

ASKED = "src/invoice.py and src/report.py read the rows of a bank's statements. Do those rows write the day first too?"
"""The question the second sub-agent asks its person."""

COMMIT = (
    "python3 tests/test_dates.py && git -c user.name=Agent -c user.email=agent@example.com commit -qam 'Read a date day first'"
)


def text(words: str) -> dict[str, Any]:
    return {"kind": "text", "text": words}


class Turns:
    """The script's turns, each a reply in the scripted provider's format."""

    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self.uses = 0

    def use(self, name: str, **given: object) -> dict[str, Any]:
        self.uses += 1
        return {"kind": "tool_use", "id": f"use_demo_{self.uses}", "name": name, "input": given}

    def turn(self, *blocks: dict[str, Any]) -> None:
        calls = any(block["kind"] == "tool_use" for block in blocks)
        self.turns.append(
            {
                "blocks": list(blocks),
                "stop_reason": "tool_use" if calls else "end_turn",
                "usage": {"input": 1200, "output": 90},
                "model": MODEL,
            }
        )


def turns() -> list[dict[str, Any]]:
    """Every turn, in the order the runner asks for them (see the docstring)."""
    say = Turns()
    use, turn = say.use, say.turn
    # 1. The lead: a baseline before anything marks it, and four sub-agents.
    turn(
        text(
            "Four questions decide this, so I'll ask four sub-agents at once: how `parse` takes a date, "
            "who calls it, whether the README and the test agree, and how an invoice falls due. "
            "First, a baseline."
        ),
        use("validate", baseline=True),
        *(use("spawn_sub_agent", title=title, objective=objective, kind="analysis") for title, objective in CHILDREN),
        use("wait_for_sub_agents"),
    )
    # 2. Each sub-agent in the order it was started.
    turn(use("read_file", path="src/dates.py"))
    turn(text("`parse` takes the month first: it reads 05/10/2026 as 10 May, though its docstring says the day comes first."))
    turn(use("search_code", pattern="parse("))
    turn(
        text("Three callers pass `parse` a date. Before I say how they write it, one question."),
        use("ask_person", question=ASKED),
    )
    turn(
        text("I'll read the README, and ask a sub-agent of my own to read the test."),
        use("read_file", path="README.md"),
        use(
            "spawn_sub_agent",
            title=TEST,
            objective="Read tests/test_dates.py and say which date it reads and what it expects of it.",
            kind="analysis",
        ),
        use("wait_for_sub_agents"),
    )
    turn(use("read_file", path="src/invoice.py"))
    turn(text("`due` takes its date from `parse`, so it follows the fix with no change of its own."))
    # 3. The lead, woken by the first, second, and fourth.
    turn(
        text(
            "Two reported: `parse` takes the month first, and `due` follows it. One asks you a question. I'll wait for the rest."
        ),
        use("wait_for_sub_agents"),
    )
    # The third's own sub-agent, then the third, woken by its report.
    turn(use("read_file", path="tests/test_dates.py"))
    turn(text("It reads 05/10/2026 and expects month 10, October: the day comes first."))
    turn(text("They agree: the README and the test both write the day first."))
    turn(
        text("The README and the test agree: the day comes first. I wait on the caller check, which needs you."),
        use("wait_for_sub_agents"),
    )
    # 4. The person answers; the second reports, and the lead rolls up.
    turn(
        text(
            "Three callers: src/invoice.py and src/report.py read the bank's rows, and the test reads 05/10/2026. "
            "Each writes the day first, as you said."
        )
    )
    turn(
        text(
            "All four reported. `parse` takes the month first, while the README, the test, and every caller "
            "write the day first. The fix is one line in `src/dates.py`."
        ),
        use("edit_file", path="src/dates.py", old_text=WRONG, new_text=RIGHT),
    )
    turn(text("I'll run the test on the fix and commit it."), use("run_command", argv=["sh", "-c", COMMIT]))
    turn(
        text("The test passes. I'll open the pull request."),
        use(
            "open_pull_request",
            title="Read a date day first",
            body="`parse` took the month first, so 05/10/2026 read as 10 May. It takes the day first now.",
        ),
    )
    turn(text("I'll validate its head."), use("validate"))
    turn(use("submit_result", claim="succeeded", evidence="$last_result.runs"))
    return say.turns


def write_script(path: Path, provider: str = "anthropic") -> None:
    """The script the runner answers from: every turn, for `provider`."""
    path.write_text(json.dumps({provider: turns()}, indent=1))


def write_repository(at: Path) -> None:
    """The repository as a bare one at `at`, its default branch holding
    `REPOSITORY`; one there already is kept."""
    if at.exists():
        return
    work = at.parent / f"{at.name}.work"
    for name, body in REPOSITORY.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(body)

    def git(*args: str, cwd: Path | None = None) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    git("init", "-q", "--bare", "-b", "main", str(at))
    git("init", "-q", "-b", "main", cwd=work)
    git("add", ".", cwd=work)
    git("-c", "user.name=Ann", "-c", "user.email=ann@example.com", "commit", "-qm", "Ledger", cwd=work)
    git("push", "-q", str(at), "main", cwd=work)
