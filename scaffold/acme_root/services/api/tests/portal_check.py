"""What the portal's browser check needs from the stack, run by the check
itself and by no gate:

    python services/api/tests/portal_check.py script <path> [--scene engineer|support]
    python services/api/tests/portal_check.py evidence <slug> <session_id>
    python services/api/tests/portal_check.py scene <root> <slug>
    python services/api/tests/portal_check.py tree <slug> [<root_id>]
    python services/api/tests/portal_check.py host <root> <slug> <session_id> <api>

`script` writes the scripted provider's script: one turn that answers in
Markdown and calls nothing, so a session runs its loop offline and the
same way every time. With `--scene engineer` it is the engineer's scene
instead: it thinks, takes its baseline, and plans; it starts two
analysis sub-agents in one answer and waits on them, the first reading
the parser and the second searching for its callers, each then
reporting; woken, it runs a failing
test, reads, edits, runs the test again, opens a pull request on the
forge's twin, asks its person, validates, and submits its result. The
runner runs one loop at a time, so the sub-agents take their turns after
their parent parks, in the order it started them. A message after that, such as a
person's giving back, gets a reply that validates the head again and
submits the result again, since an engineer's loop ends only on its
result. Its baseline runs before anything marks the session. Each
command and each later validation wait for a decision, since a tool's
output, such as its plan's answer, marks it. With `--scene support` it is
the platform assistant answering in the support dock: it searches its
corpus, then answers with a link to a page of the portal and a link to
another site.
`evidence` records on one session of the org what an executor writes: two
runs of a check and a validation of one of them. The local stack runs no
executor, so the check writes the records its evidence screen reads
through the om, under the org's owner. `scene` makes what the engineer's
scene runs on: the org's first repository as a bare one under `<root>`
(`portal_stack.py` clones from there), holding a parser whose test fails,
and the validation policy of the org's first project. `tree` starts the
scene's engineer for the org's owner and writes its tree straight through
storage, for what the scene does not reach, a sub-agent that asks its
person: one answer that starts
two, each in a slot its tree's bounds hold, and a park on them; the first
reads, ends, and reports; the second still searches. It prints the ids
of the root and its sub-agents. Given the root, it plays the next beat:
the sub-agent at work asks its person and parks on their answer; called
again, it takes the answer and ends. Each beat reports to the root, as the
engine does, and no step it writes asks for a run. `host` stands in for the host that holds the session's
workspace, which the local stack runs none of: it enrolls a host in a
pool of the org's, places the session there and binds its workspace to
a clone of the scene's repository at the branch the engineer pushed,
prints `ready`, then claims the first command a person sends over the
API's host routes at `<api>`, runs it there, settles it, and takes the
session back off the pool."""

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta
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

# The tree `tree` writes: what its person asks the engineer, the engineer's
# answer that starts two sub-agents, and each sub-agent's title and
# objective.
TREE_ASK = "Read every date in the app day first"
SPLIT = (
    "Two things decide this, so I'll ask two sub-agents at once: one reads how the "
    "other parsers take a date, the other finds every caller of `parse`. I change "
    "the parser once both report."
)
CHILDREN = (
    (
        "Read how the other parsers take a date",
        "Read each parser under src/ and say in which order it reads a date.",
    ),
    (
        "Check every caller of parse",
        "Find every caller of parse and say which of them pass a date month first.",
    ),
)
PARSERS = (
    "src/dates.py:4:def parse(text):\n"
    "src/times.py:9:def parse_time(text):\n"
    "src/money.py:12:def parse_amount(text):"
)
READ = "Only `parse` in src/dates.py reads a date, and it takes the month first."
CALLERS = (
    'src/report.py:21:    when = parse(row["date"])\n'
    "scripts/import_us.py:8:    day = parse(line)\n"
    'tests/test_dates.py:5:    assert parse("03/04/2026")'
)
ASKED = (
    "scripts/import_us.py reads files from a US bank, written month first. "
    "Should it keep reading them that way?"
)
ANSWERED = "Yes, leave that script month first."
FOUND = (
    "Two callers pass a date for `parse` to read: src/report.py and tests/test_dates.py. "
    "scripts/import_us.py stays month first, as you said."
)

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
    "\n"
    "def test_day_first():\n"
    '    assert parse("05/10/2026").month == 10, "the month is the second part"\n'
    "\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    test_day_first()\n"
    '    print("1 passed")\n'
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
    "I'll ask two sub-agents what decides the fix, run the failing test to see it fail, "
    "then read the parser. "
    "The fix should be one line: the parts of the date in the order it is written. "
    "Here is the plan."
)
AFTER = "I read what you did. The test passes on the branch, so nothing else changes. I'll validate the head again."
PLAN = (
    "1. Ask two sub-agents how the parser takes a date and who calls it.\n"
    "2. Run `tests/test_dates.py` and see it fail.\n"
    "3. Read `src/dates.py` and take the day first.\n"
    "4. Run the test again and commit.\n"
    "5. Open a pull request, validate its head, and submit the result."
)
CALLED = (
    "One caller passes `parse` a date: tests/test_dates.py, with 05/10/2026, written day first."
)
BOTH = (
    "Both reported: `parse` takes the month first, and its one caller writes the day "
    "first. I'll run the failing test."
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
        # The baseline before anything changes, in the first turn: a turn of
        # its own would park the session's pause before its plan.
        turn(
            ThinkingBlock(text=THOUGHT),
            TextBlock(text=OPENING),
            use("validate", baseline=True),
            use("write_plan", plan=PLAN),
        ),
        turn(
            TextBlock(text=SPLIT),
            *(
                use("spawn_sub_agent", title=title, objective=objective, kind="analysis")
                for title, objective in CHILDREN
            ),
            use("wait_for_sub_agents"),
        ),
        # The first sub-agent's loop, then the second's, once their parent parks.
        turn(use("read_file", path="src/dates.py")),
        turn(TextBlock(text=READ)),
        turn(use("search_code", pattern="parse(")),
        turn(TextBlock(text=CALLED)),
        # Woken by the second report, the parent goes on.
        turn(TextBlock(text=BOTH), use("run_command", argv=["python3", "tests/test_dates.py"])),
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
        turn(TextBlock(text=AFTER), use("validate")),
        turn(use("submit_result", claim="succeeded", evidence="$last_result.runs")),
    ]


SUPPORT_ANSWER = (
    "It waits on its two sub-agents, and goes on once both report. "
    "Each one's place is on [all sessions](/sessions), and the "
    "[platform guide](https://example.com/guide) says how a tree waits."
)


def support_scene() -> list[Any]:
    """The platform assistant's turns in the support dock: a search of its
    corpus, then an answer that links a page of the portal and another
    site."""
    from acme.integrations.model_providers.calls import ModelReply
    from acme.integrations.model_providers.content import TextBlock, ToolUseBlock
    from acme.integrations.model_providers.types import StopReason, Usage

    search = ToolUseBlock(
        id="use_support_1",
        name="search_corpus",
        input={"query": "a session waits on its sub-agents"},
    )
    return [
        ModelReply(
            blocks=(search,),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input=900, output=30),
            model=SONNET,
        ),
        ModelReply(
            blocks=(TextBlock(text=SUPPORT_ANSWER),),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input=1400, output=60),
            model=SONNET,
        ),
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
    scenes = {"engineer": engineer_scene, "support": support_scene}
    turns: list[Turn] = scenes[scene]() if scene is not None else [reply]
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
        owner = await container.managers.tenancy.delegated_context(
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
        owner = await container.managers.tenancy.delegated_context(
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


def story(session: Any, person: Any, at: datetime) -> Any:
    """A history of `session` as its runs write it, a few seconds apart: the
    test suites' `History`, each step a real `Step` that storage numbers."""
    from contracts.histories import History

    from acme.om.attribution.types.principal import AgentRef
    from acme.om.steps.types.step import Step

    class Story(History):
        def __init__(self) -> None:
            super().__init__(session.id)
            self.person = person
            self.at = at

        @property
        def agent(self) -> AgentRef:
            return AgentRef(kind=session.kind, version=session.kind_version, session_id=session.id)

        def then(self) -> datetime:
            self.at += timedelta(seconds=3)
            return self.at

        def add(self, **fields: Any) -> Step:
            step = super().add(**fields).model_copy(update={"created_at": self.then(), "seq": 0})
            self.steps[-1] = step
            return step

        def asks(self, use_id: str, tool: str, given: dict[str, Any], text: str = "") -> Step:
            """A model call on what came last, answering `text` and calling
            `tool` once: its call."""
            request = self.request(self.steps[-1:])
            return self.call(self.response(request, text, [(use_id, tool, given)]), use_id, tool)

    return Story()


async def scene_owner(slug: str) -> tuple[Any, Any]:
    """The scene's container, started, and its org's owner."""
    from portal_stack import scene_container

    from acme.services.api.container import boot
    from acme.services.api.main import command_request
    from acme.services.api.settings import ApiSettings

    settings = ApiSettings()
    boot(settings)
    settings.refuse_remote()
    container = scene_container(settings)
    await container.start()
    org = await container.storage.get_tenancy_storage().read_org_by_slug(slug)
    if org is None:
        await container.close()
        raise SystemExit(f"no org {slug}")
    owner = await container.managers.tenancy.delegated_context(
        command_request(settings), org.id, org.created_by
    )
    return container, owner


async def written(container: Any, owner: Any, session_id: UUID, steps: list[Any]) -> None:
    """Steps appended as one run writes them, then the session's status
    brought up to them once: a park or a run's end asks for no run."""
    managers = container.managers
    epoch = await managers.steps.begin_run(owner, session_id)
    await managers.steps.append_steps(owner, session_id, epoch, steps)
    await managers.agent_sessions.project_status(owner, session_id)


async def write_tree(slug: str) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from acme.om.agent_sessions.rules import parked_step
    from acme.om.agent_sessions.types.agent_session import AgentSession, SessionStatus
    from acme.om.agents.loop_rules import ended_step
    from acme.om.agents.types.report import Report
    from acme.om.agents.types.request import Start
    from acme.om.attribution.types.authority import AuthorityMode
    from acme.om.attribution.types.principal import AgentRef, Principal, PrincipalKind
    from acme.om.base import new_id, utcnow
    from acme.om.platform_agents.kinds import ANALYSIS, ENGINEER
    from acme.om.steps.types.content import Content, TextBlock
    from acme.om.steps.types.header import InputHeader, LoopOutcome, Park, ParkReason
    from acme.om.steps.types.step import Actor, Origin, Step, StepType

    container, owner = await scene_owner(slug)
    try:
        managers = container.managers
        trees = container.storage.get_agent_storage()
        person = Principal(kind=PrincipalKind.PERSON, id=owner.user_id)
        # The tree began a minute ago: its sessions and their steps alike.
        began = utcnow() - timedelta(minutes=1)

        # The root: the scene's engineer, whose tree holds ten sub-agents.
        root = await managers.agents.start_session(
            owner, Start(id=new_id(), kind=ENGINEER, title=TREE_ASK)
        )
        told = story(root, person, began)
        ids = [new_id() for _ in CHILDREN]
        uses = [
            (f"toolu_spawn_{n}", "spawn_sub_agent", {"title": t, "objective": o, "kind": ANALYSIS})
            for n, (t, o) in enumerate(CHILDREN, 1)
        ]
        response = told.response(told.request([told.message(TREE_ASK)]), SPLIT, uses)
        for (use_id, tool, _), child_id in zip(uses, ids, strict=True):
            told.result(told.call(response, use_id, tool), f'{{"session_id": "{child_id}"}}')
        # Its own unlock, never the engine's: a report then leaves the root
        # parked, so no step asks for a run that would take the scene's turns.
        waits = Park(reason=ParkReason.CHILDREN, unlock="children")
        told.steps.append(parked_step(new_id(), root.id, told.loop_id, waits, told.then()))

        # Its sub-agents, each in a slot of the tree, at work from the start.
        children: list[tuple[Any, Any]] = []
        for n, (child_id, (title, objective)) in enumerate(zip(ids, CHILDREN, strict=True)):
            if await trees.take_slot(owner.org_id, root.root_id) is None:
                raise SystemExit("the tree holds no more sub-agents")
            # A second apart, so they list in the order the answer started them.
            made = began + timedelta(seconds=n)
            child = AgentSession(
                id=child_id,
                created_at=made,
                updated_at=made,
                created_by=owner.user_id,
                updated_by=owner.user_id,
                title=title,
                participants=(owner.user_id,),
                kind=ANALYSIS,
                kind_version=1,
                parent_id=root.id,
                root_id=root.root_id,
                depth=root.depth + 1,
                status=SessionStatus.RUNNING,
            )
            sessions = container.storage.get_agent_session_storage()
            await sessions.create_session(owner.org_id, child, ())
            await managers.attribution.open_authority(owner, child_id, AuthorityMode.STEADY)
            work = story(child, person, began)
            parent = AgentRef(kind=root.kind, version=root.kind_version, session_id=root.id)
            aim = Step(
                id=new_id(),
                created_at=work.then(),
                session_id=child_id,
                loop_id=child_id,
                type=StepType.MESSAGE,
                actor=Actor.AGENT,
                origin=Origin.PARENT,
                header=InputHeader(waking=True, principal=person, agent=parent),
                content=Content(blocks=(TextBlock(text=objective),)),
            )
            work.steps.append(aim)
            work.loop_id = aim.id
            children.append((child, work))
        await written(container, owner, root.id, told.steps)

        # The first reads the parsers, ends, and reports to the root.
        first, read = children[0]
        call = read.asks("toolu_parsers", "search_code", {"pattern": "def parse", "path": "src"})
        read.result(call, PARSERS)
        read.response(read.request(read.steps[-1:]), READ)
        read.steps.append(
            ended_step(new_id(), read.then(), first.id, read.loop_id, LoopOutcome.SUCCEEDED)
        )
        await written(container, owner, first.id, read.steps)
        report = Report(loop_id=read.loop_id, outcome=LoopOutcome.SUCCEEDED, answer=READ)
        await managers.agents.report_to_parent(owner, first.id, report)

        # The second is still searching.
        second, search = children[1]
        search.asks("toolu_callers", "search_code", {"pattern": "parse(", "path": "."})
        await written(container, owner, second.id, search.steps)
        print(json.dumps({"root": str(root.id), "children": [str(one) for one in ids]}))
    finally:
        await container.close()


async def next_beat(slug: str, root_id: UUID) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from acme.om.agent_sessions.rules import QUESTION, parked_step
    from acme.om.agent_sessions.types.agent_session import SessionStatus
    from acme.om.agents.loop_rules import ended_step
    from acme.om.agents.types.report import Report
    from acme.om.attribution.types.principal import Principal, PrincipalKind
    from acme.om.base import new_id, utcnow
    from acme.om.steps.types.header import LoopOutcome
    from acme.om.steps.types.step import StepType

    container, owner = await scene_owner(slug)
    try:
        managers = container.managers
        page = await managers.agent_sessions.get_children(owner, root_id, None, 10)
        working = [one for one in page.items if one.status is SessionStatus.RUNNING]
        asking = [one for one in page.items if one.park == QUESTION]
        child = (working or asking or [None])[0]
        if child is None:
            raise SystemExit(f"no sub-agent of {root_id} is at work or asks")
        held = (await managers.steps.get_steps(owner, child.id, 0, 100)).items
        person = Principal(kind=PrincipalKind.PERSON, id=owner.user_id)
        work = story(child, person, max(utcnow(), held[-1].created_at))
        work.loop_id = held[-1].loop_id
        if working:
            # Its search answers, and it asks its person.
            call = next(step for step in reversed(held) if step.type is StepType.TOOL_REQUEST)
            work.result(call, CALLERS)
            asked = work.asks("toolu_ask", "ask_person", {"question": ASKED})
            work.result(asked, json.dumps({"question": ASKED}))
            work.steps.append(parked_step(new_id(), child.id, work.loop_id, QUESTION, work.then()))
            report = Report(loop_id=work.loop_id, park=QUESTION)
        else:
            # Its person answers, and it ends.
            work.response(work.request([work.message(ANSWERED)]), FOUND)
            work.steps.append(
                ended_step(new_id(), work.then(), child.id, work.loop_id, LoopOutcome.SUCCEEDED)
            )
            report = Report(loop_id=work.loop_id, outcome=LoopOutcome.SUCCEEDED, answer=FOUND)
        await written(container, owner, child.id, work.steps)
        # What it does now reaches its parent, as the engine reports it.
        await managers.agents.report_to_parent(owner, child.id, report)
        print(child.id)
    finally:
        await container.close()


def checkout(root: Path, slug: str, at: Path) -> Path:
    """A clone of the org's repository at the branch pushed last, else its
    default branch: what the session's workspace holds once it delivered."""
    from acme.services.api.seed import first_repository

    repository = first_repository(slug)
    bare = root / repository.host / f"{repository.path}.git"
    heads = subprocess.run(
        ["git", "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)", "refs/heads"],
        cwd=bare,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    branch = next((head for head in heads if head != "main"), "main")
    subprocess.run(
        ["git", "clone", "-q", "--branch", branch, str(bare), str(at)],
        check=True,
        capture_output=True,
    )
    return at


async def stand_in_host(root: Path, slug: str, session_id: UUID, api: str) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    import httpx
    from contracts.hosts_storage import make_pool

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
        owner = await container.managers.tenancy.delegated_context(
            command_request(settings), org.id, org.created_by
        )
        hosts = container.managers.hosts
        pool = await hosts.create_pool(owner, make_pool("this machine"))
        issued = await hosts.issue_enrollment_token(owner, pool.id)
        async with httpx.AsyncClient(base_url=api, timeout=30) as client:
            enrolled = await client.post(
                "/v1/hosts/enrollments",
                headers=host_headers(issued.token),
                json={"name": "this-machine", "advertisement": ADVERTISED, "exec_version": 1},
            )
            enrolled.raise_for_status()
            host = enrolled.json()
            await hosts.place_session(owner, session_id, pool.id)
            work = checkout(root, slug, root / "hands" / str(session_id))
            await container.managers.relay.bind_workspace(
                owner, session_id, UUID(host["host_id"]), str(work)
            )
            print("ready", flush=True)
            try:
                await run_one(client, host_headers(host["token"]), work)
            finally:
                await hosts.place_session(owner, session_id, None)
    finally:
        await container.close()


ADVERTISED = {
    "os": "this machine",
    "shell": "/bin/sh",
    "capabilities": ["git"],
    "isolation_modes": ["directory"],
}


def host_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-App": "api",
        "X-App-Version": "host@portal-check",
    }


async def run_one(client: Any, headers: dict[str, str], work: Path) -> None:
    """Claims the first command sent within two minutes, runs it in `work`,
    and settles it with what it printed."""
    import base64
    import hashlib

    from acme.om.relay.types.exec import ExecOutcome, ExecOutput, ExecResult

    for _ in range(240):
        claimed = await client.post(
            "/v1/hosts/me/claims", headers=headers, json={"exec_version": 1}
        )
        claimed.raise_for_status()
        item = claimed.json().get("item")
        if item is not None:
            break
        await asyncio.sleep(0.5)
    else:
        raise SystemExit("no command came")
    item_id = item["payload"]["item_id"]
    held = await client.get(f"/v1/hosts/me/exec/{item_id}", headers=headers)
    held.raise_for_status()
    request = held.json()["request"]
    ran = await asyncio.to_thread(
        subprocess.run,
        request["argv"],
        cwd=work / request.get("cwd", "."),
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"ran {' '.join(request['argv'])}: exit {ran.returncode}", flush=True)
    settled = ExecResult(
        outcome=ExecOutcome(exit_code=ran.returncode),
        output=ExecOutput(stdout=ran.stdout, stderr=ran.stderr),
    )
    data = settled.model_dump_json().encode()
    pushed = await client.post(
        f"/v1/hosts/me/exec/{item_id}/result",
        headers=headers,
        json={
            "data": base64.b64encode(data).decode(),
            "crossing": {
                "kind": "result",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            },
        },
    )
    pushed.raise_for_status()


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
    if len(argv) == 2 and argv[0] == "tree":
        asyncio.run(write_tree(argv[1]))
        return 0
    if len(argv) == 3 and argv[0] == "tree":
        asyncio.run(next_beat(argv[1], UUID(argv[2])))
        return 0
    if len(argv) == 5 and argv[0] == "host":
        asyncio.run(stand_in_host(Path(argv[1]), argv[2], UUID(argv[3]), argv[4]))
        return 0
    if len(argv) == 3 and argv[0] == "evidence":
        asyncio.run(record_evidence(argv[1], UUID(argv[2])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
