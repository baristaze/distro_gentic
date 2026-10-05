"""What the portal's browser check needs from the stack, run by the check
itself and by no gate:

    python services/api/tests/portal_check.py script <path> [--scene engineer]
    python services/api/tests/portal_check.py evidence <slug> <session_id>
    python services/api/tests/portal_check.py scene <root> <slug>

`script` writes the scripted provider's script: one turn that answers in
Markdown and calls nothing, so a session runs its loop offline and the
same way every time. With `--scene engineer` it is the engineer's scene
instead: it thinks, plans, runs a failing test, reads, edits, runs the
test again, opens a pull request on the forge's twin, asks its person,
validates, and submits its result. Each command and the validation wait
for a decision, since its plan's answer, a tool's output, marks it.
`evidence` records on one session of the org what an executor writes: two
runs of a check and a validation of one of them. The local stack runs no
executor, so the check writes the records its evidence screen reads
through the om, under the org's owner. `scene` makes what the engineer's
scene runs on: the org's first repository as a bare one under `<root>`
(`portal_stack.py` clones from there), holding a parser whose test fails,
and the validation policy of the org's first project."""

import asyncio
import subprocess
import sys
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID

REPO = Path(__file__).resolve().parents[3]

ANSWER = (
    "Done. The docs now read in **one voice**.\n\n"
    "- The README opens on what the product does.\n"
    "- Every command runs as written: `make check`.\n"
)


SONNET = "claude-sonnet-5-5"

PARSER = (
    "from datetime import date\n"
    "\n"
    "\n"
    "def parse(text):\n"
    '    """A date written day first, as 05/10/2026."""\n'
    '    month, day, year = text.split("/")\n'
    "    return date(int(year), int(month), int(day))\n"
)
TEST = (
    "import sys\n"
    "\n"
    'sys.path.insert(0, "src")\n'
    "from dates import parse  # noqa: E402\n"
    "\n"
    'assert parse("05/10/2026").month == 10, "the month is the second part"\n'
    'print("1 passed")\n'
)
WRONG = '    month, day, year = text.split("/")\n'
RIGHT = '    day, month, year = text.split("/")\n'
COMMITS = (
    "python3 tests/test_dates.py"
    " && git -c user.name=Engineer -c user.email=engineer@example.test"
    " commit -qam 'Read a date day first'"
)

THOUGHT = (
    "The test reads 05/10/2026 and expects October, so the date is written day first. "
    "If the parser takes the month first, it reads May and the assertion fails. "
    "I should run the test before I change anything, so the failure is on record, "
    "then read the parser and change only the order of the parts."
)
OPENING = (
    "I'll run the failing test first to see it fail, then read the parser. "
    "The fix should be one line: the parts of the date in the order it is written. "
    "Here is the plan."
)
PLAN = (
    "1. Run `tests/test_dates.py` and see it fail.\n"
    "2. Read `src/dates.py` and take the day first.\n"
    "3. Run the test again and commit.\n"
    "4. Open a pull request, validate its head, and submit the result."
)


def engineer_scene() -> list[Any]:
    """The engineer's turns, in order (see the module's docstring)."""
    from acme.integrations.model_providers.calls import ModelReply
    from acme.integrations.model_providers.content import TextBlock, ThinkingBlock, ToolUseBlock
    from acme.integrations.model_providers.types import StopReason, Usage

    ids = count(1)

    def use(name: str, **asked: object) -> ToolUseBlock:
        return ToolUseBlock(id=f"use_scene_{next(ids)}", name=name, input=asked)

    def turn(*blocks: Any) -> ModelReply:
        """A turn of `blocks` in order, a thought held apart at its place."""
        main = tuple(block for block in blocks if not isinstance(block, ThinkingBlock))
        thought = tuple(
            block.model_copy(update={"at": sum(1 for b in blocks[:at] if b in main)})
            for at, block in enumerate(blocks)
            if isinstance(block, ThinkingBlock)
        )
        calls = any(isinstance(block, ToolUseBlock) for block in main)
        return ModelReply(
            blocks=main,
            thinking=thought,
            stop_reason=StopReason.TOOL_USE if calls else StopReason.END_TURN,
            usage=Usage(input=1200, output=90),
            model=SONNET,
        )

    return [
        turn(ThinkingBlock(text=THOUGHT), TextBlock(text=OPENING), use("write_plan", plan=PLAN)),
        turn(use("run_command", argv=["python3", "tests/test_dates.py"])),
        turn(
            ThinkingBlock(text="It read May: the parser takes the month first."),
            use("read_file", path="src/dates.py"),
        ),
        turn(use("edit_file", path="src/dates.py", old_text=WRONG, new_text=RIGHT)),
        turn(use("run_command", argv=["sh", "-c", COMMITS])),
        turn(
            TextBlock(text="The test passes. I'll open the pull request."),
            use(
                "open_pull_request",
                title="Read a date day first",
                body="`parse` took the month first, so 05/10/2026 read as May. It reads the day first now.",
            ),
        ),
        turn(use("ask_person", question="Shall I also add a test for a leap day, 29/02/2028?")),
        turn(ThinkingBlock(text="Not now, then. I'll validate the head."), use("validate")),
        turn(use("submit_result", claim="succeeded", evidence="$last_result.runs")),
    ]


def write_script(path: Path, scene: str | None = None) -> None:
    from acme.integrations.model_providers.calls import ModelReply
    from acme.integrations.model_providers.content import TextBlock
    from acme.integrations.model_providers.scripted import SCRIPT, Turn
    from acme.integrations.model_providers.types import ProviderName, StopReason, Usage

    reply = ModelReply(
        blocks=(TextBlock(text=ANSWER),),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input=160, output=40),
        model=SONNET,
    )
    turns: list[Turn] = engineer_scene() if scene == "engineer" else [reply]
    path.write_bytes(SCRIPT.dump_json({ProviderName.ANTHROPIC: turns}))


def bare_repository(at: Path) -> None:
    """The bound repository on this host, its default branch holding the
    parser and its failing test, and ignoring what a run of the test
    leaves, so a validation finds the tree clean; one made before is
    kept."""
    if at.exists():
        return
    work = at.parent / f"{at.name}.work"
    (work / "src").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "src" / "dates.py").write_text(PARSER)
    (work / "tests" / "test_dates.py").write_text(TEST)
    # A host workspace is its command's home, where macOS's Python keeps
    # its caches too.
    (work / ".gitignore").write_text("__pycache__/\n/Library/Caches/\n")

    def git(*args: str, cwd: Path | None = None) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    git("init", "-q", "--bare", "-b", "main", str(at))
    git("init", "-q", "-b", "main", cwd=work)
    git("add", ".", cwd=work)
    git(
        "-c",
        "user.name=Ann",
        "-c",
        "user.email=ann@example.test",
        "commit",
        "-qm",
        "Dates",
        cwd=work,
    )
    git("push", "-q", str(at), "main", cwd=work)


async def prepare_scene(root: Path, slug: str) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from contracts.evidence_storage import make_policy

    from acme.om.evidence.rules import policy_key
    from acme.services.api.container import AppContainer, boot
    from acme.services.api.main import command_request
    from acme.services.api.seed import first_repository
    from acme.services.api.settings import ApiSettings

    repository = first_repository(slug)
    bare_repository(root / repository.host / f"{repository.path}.git")
    settings = ApiSettings()
    boot(settings)
    settings.refuse_remote()
    container = AppContainer.build(settings)
    await container.start()
    try:
        org = await container.storage.get_tenancy_storage().read_org_by_slug(slug)
        if org is None:
            raise SystemExit(f"no org {slug}")
        owner = await container.managers.tenancy.member_context(
            command_request(settings), org.id, org.created_by
        )
        projects = await container.managers.projects.list_projects(owner, None, 10)
        if not projects:
            raise SystemExit(f"org {slug} has no project")
        policy = make_policy(policy_key(projects[0].id))
        await container.managers.evidence.write_policy(owner, policy)
    finally:
        await container.close()


async def record_evidence(slug: str, session_id: UUID) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from contracts.evidence_storage import make_record, make_validation

    from acme.om.evidence.types.provenance import Provenance
    from acme.om.evidence.types.record import RunOutcome
    from acme.services.api.container import AppContainer, boot
    from acme.services.api.main import command_request
    from acme.services.api.settings import ApiSettings

    settings = ApiSettings()
    boot(settings)
    settings.refuse_remote()
    container = AppContainer.build(settings)
    await container.start()
    try:
        org = await container.storage.get_tenancy_storage().read_org_by_slug(slug)
        if org is None:
            raise SystemExit(f"no org {slug}")
        owner = await container.managers.tenancy.member_context(
            command_request(settings), org.id, org.created_by
        )
        await container.managers.agent_sessions.get_session(owner, session_id)
        evidence = container.managers.evidence
        await evidence.record_run(owner, make_record(session_id, check="unit"))
        await evidence.record_run(
            owner,
            make_record(
                session_id, check="browser", outcome=RunOutcome.FAILED, provenance=Provenance.TWIN
            ),
        )
        validation, validated = make_validation(session_id, 1)
        await container.storage.get_evidence_storage().create_validation(
            owner.org_id, validation, validated
        )
    finally:
        await container.close()


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "script":
        write_script(Path(argv[1]))
        return 0
    if len(argv) == 4 and argv[0] == "script" and argv[2] == "--scene":
        write_script(Path(argv[1]), argv[3])
        return 0
    if len(argv) == 3 and argv[0] == "scene":
        asyncio.run(prepare_scene(Path(argv[1]), argv[2]))
        return 0
    if len(argv) == 3 and argv[0] == "evidence":
        asyncio.run(record_evidence(argv[1], UUID(argv[2])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
