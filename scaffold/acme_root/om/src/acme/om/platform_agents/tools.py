"""The tools the shipped kinds call. Each declares its class and its effect,
which is all policy reads of it, and takes a typed input that refuses a
field it does not declare: what a model writes is checked before any of it
runs.

The workspace's tools reach the world only through the call's runtime, so
a kind with no workspace cannot use one even when it is handed one: an
edit reads and writes its file there, and a search of the code runs there,
bounded in its matches and its bytes, never in the platform's process. The
engineer's pull request opens its own branch on its project's repository
with a push token the platform mints for the call and checks before it
writes; the model names neither the branch nor the repository, and never
sees the token. The branch and the pull request are bound to the session,
and the push recorded as its act, so the events on them find it. The
assistant's read the corpus and the tenant's live records through the
asking person's own permissions, never a session's content, and draft;
the one that hands work on starts a session that waits for its person. The knowledge tools
reach the reviewed entries of the session's project and of its whole
tenant, and the platform's own documentation, its corpus; a suggestion
waits for a person's review. A tool that reads a manager takes it late, as
a callable the root answers once it has built it."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import SessionStatus
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.agents.types.request import MAX_TITLE, Handoff
from acme.om.agents.types.result import Claim
from acme.om.automations import AutomationsManagerInterface
from acme.om.automations.types.automation import Automation
from acme.om.automations.types.automation import Limits as AutomationLimits
from acme.om.base import Platform
from acme.om.context import Role, TenantContext
from acme.om.evidence import EvidenceManagerInterface
from acme.om.evidence.rules import PATHS
from acme.om.evidence.types.record import RunPurpose
from acme.om.exceptions import (
    Conflict,
    NotAuthorized,
    NotFound,
    ToolFailed,
    Unavailable,
    ValidationFailed,
)
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import HostStatus
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.tools import FORGE
from acme.om.intake.types.link import HandleKind
from acme.om.knowledge import KnowledgeManagerInterface
from acme.om.knowledge.types.knowledge import MAX_TEXT, Knowledge
from acme.om.notifications.rules import held_calls
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.types.corpus import Corpus, Passage
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.projects import ProjectsManagerInterface
from acme.om.projects.types.project import Project
from acme.om.relay import RelayManagerInterface
from acme.om.steps import StepsManagerInterface
from acme.om.steps.types.content import MAX_NAME
from acme.om.steps.types.header import ParkReason, ToolFailure, ToolRequestHeader
from acme.om.steps.types.step import Step
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.rules import approver_roles
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import ApproverRule, PolicyRule, Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkKind, WorkStatus
from acme.om.workspaces import WorkspacesManagerInterface
from acme.om.workspaces.rules import COMMIT

MAX_PATH = 1024
MAX_READ = 200_000  # bytes one read takes at most
MAX_EDIT = MAX_READ  # bytes of a file one edit reads and writes back, at most
# The most matches one search of the code answers, each cut at its width:
# the whole answer stays inside what the model reads of one output.
MAX_MATCHES = 100
MAX_MATCH_TEXT = 200
MAX_SEARCH_OUTPUT = 400_000  # characters of the search's output it reads, at most
NO_NUL = r"^[^\x00]*$"
# A line break splits grep's pattern into several, any of which matches, and
# an empty one matches every line: a search's pattern is one line.
ONE_LINE = r"^[^\x00\r\n]*$"


class NativeToolImpl(ToolInterface):
    """A tool of the platform's own code: it acts on nothing a target names,
    and has nothing to refuse before a person is asked."""

    SPEC: ClassVar[ToolSpec]

    @property
    def spec(self) -> ToolSpec:
        return self.SPEC

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        return Target()

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        return None


# The workspace.


class PathInput(ToolInput):
    path: str = Field(default=".", min_length=1, max_length=MAX_PATH)


class Entry(Platform):
    path: str
    is_dir: bool
    size: int


class Entries(Platform):
    entries: tuple[Entry, ...]


class ListFilesImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_FILES,
        description="Lists the files under a path of the workspace, at most 500.",
        input_model=PathInput,
        output_model=Entries,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PathInput)
        found = await runtime.list_files(call_input.path, 500)
        return Entries(
            entries=tuple(Entry(path=e.path, is_dir=e.is_dir, size=e.size) for e in found)
        )


class Text(Platform):
    text: str


class ReadFileImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.READ_FILE,
        description="Reads a text file of the workspace, its first 200,000 bytes.",
        input_model=PathInput,
        output_model=Text,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PathInput)
        data = await runtime.read_file(call_input.path, MAX_READ)
        return Text(text=data.decode(errors="replace"))


class WriteInput(ToolInput):
    path: str = Field(min_length=1, max_length=MAX_PATH)
    text: str


class Written(Platform):
    path: str
    size: int


class EditInput(ToolInput):
    """One place in a file: `old_text`, which must match exactly one place,
    or the lines `start_line` to `end_line`, counted from 1, both included."""

    path: str = Field(min_length=1, max_length=MAX_PATH)
    new_text: str = Field(max_length=MAX_EDIT)
    old_text: str | None = Field(default=None, min_length=1, max_length=MAX_EDIT)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_place(self) -> Self:
        by_lines = self.start_line is not None or self.end_line is not None
        if (self.old_text is not None) == by_lines:
            raise ValueError("an edit names old_text or a line range, never both")
        if by_lines and (
            self.start_line is None or self.end_line is None or self.start_line > self.end_line
        ):
            raise ValueError("a line range names start_line and end_line, the start first")
        return self


class Edited(Platform):
    path: str
    line: int  # where the new text starts
    lines: int  # how many lines the new text holds there
    size: int


class FileChangeImpl(NativeToolImpl):
    """A tool that changes one file of the workspace, by the path its input
    names. A path the policy of the session's project protects is refused at
    the call, before anyone is asked: the evidence reads it (`protection`)
    from the session's project, never from the input."""

    def __init__(self, evidence: Callable[[], EvidenceManagerInterface]) -> None:
        self._evidence = evidence

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        # The engine asks a tool's target with no session, and the session's
        # project is what protects a path, so the refusal is made here.
        assert isinstance(call_input, WriteInput | EditInput)
        target = await self._evidence().protection(ctx, runtime.session_id, [call_input.path])
        if target.kind == PATHS and target.attributes.get("protected"):
            raise ToolFailed(
                ToolFailure.DENIED,
                f"{call_input.path} is protected by the project's validation policy: "
                "it is never changed by an agent",
            )


class WriteFileImpl(FileChangeImpl):
    """Writes one file of the workspace whole."""

    SPEC = ToolSpec(
        name=kinds.WRITE_FILE,
        description="Writes a text file of the workspace whole, creating it if it is missing.",
        input_model=WriteInput,
        output_model=Written,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.WRITE,
        effect=Effect.IDEMPOTENT,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, WriteInput)
        data = call_input.text.encode()
        await runtime.write_file(call_input.path, data)
        return Written(path=call_input.path, size=len(data))


class EditFileImpl(FileChangeImpl):
    """Replaces one place in a text file of the workspace and leaves the rest
    of it as it was. A match of more than one place is refused, so an edit
    never lands where the model did not mean. A repeat of a call could
    change a range twice, so a call whose run was lost is never run again."""

    SPEC = ToolSpec(
        name=kinds.EDIT_FILE,
        description=(
            "Replaces one place in a text file of the workspace with new_text, and leaves "
            "the rest of the file as it was. Name the place by old_text, copied exactly "
            "from the file, which must match one place only: a match of more than one is "
            "refused, so give more of the text around it. Or name it by start_line and "
            "end_line, counted from 1, both included. Answers the line the new text starts "
            "on and how many lines it holds."
        ),
        input_model=EditInput,
        output_model=Edited,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.WRITE,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, EditInput)
        path = call_input.path
        data = await runtime.read_file(path, MAX_EDIT + 1)
        if len(data) > MAX_EDIT:
            raise ToolFailed(
                ToolFailure.PERMANENT,
                f"{path} is past the {MAX_EDIT:,} bytes an edit takes: write it whole",
            )
        try:
            text = data.decode()
        except UnicodeDecodeError:
            raise ToolFailed(ToolFailure.PERMANENT, f"{path} is not UTF-8 text") from None
        edit = rules.edited(
            text,
            call_input.new_text,
            old_text=call_input.old_text,
            start_line=call_input.start_line,
            end_line=call_input.end_line,
        )
        if isinstance(edit, str):
            raise ToolFailed(ToolFailure.PERMANENT, f"{path}: {edit}")
        written = edit.text.encode()
        await runtime.write_file(path, written)
        return Edited(path=path, line=edit.line, lines=edit.lines, size=len(written))


class SearchCodeInput(ToolInput):
    pattern: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    path: str = Field(default=".", min_length=1, max_length=MAX_PATH, pattern=NO_NUL)
    limit: int = Field(default=50, ge=1, le=MAX_MATCHES)

    @field_validator("path")
    @classmethod
    def _inside(cls, path: str) -> str:
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("a path inside the workspace: never absolute, never through ..")
        return path


class Match(Platform):
    path: str
    line: int
    text: str


class Matches(Platform):
    matches: tuple[Match, ...]
    more: bool  # matches past the bound were left out


class SearchCodeImpl(NativeToolImpl):
    """Searches the files under a path of the workspace for a pattern, with
    the workspace's own grep, through the transport: wherever the session's
    workspace runs, never in the platform's process. Each file answers at
    most the limit, the answer at most the limit in all, each line cut at
    its width, and the output read at most its bound, so a search never
    floods the model's window. A path is the workspace's, never absolute
    and never climbing out."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_CODE,
        description=(
            "Searches the text files under a path of the workspace, the whole of it by "
            "default, for an extended regular expression. Answers each matching line with "
            "its file and its line number, at most limit of them, each cut at 200 "
            "characters, and whether more were left out: narrow the pattern or the path "
            "when they were."
        ),
        input_model=SearchCodeInput,
        output_model=Matches,
        timeout=timedelta(seconds=60),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SearchCodeInput)
        argv = (
            "grep",
            "-r",
            "-n",
            "-I",
            "-E",
            "--null",
            # Named on every match: grep names none when its path is one file.
            "--with-filename",
            f"--max-count={call_input.limit}",
            "--exclude-dir=.git",
            "-e",
            call_input.pattern,
            "--",
            call_input.path,
        )
        result = await runtime.run(argv, max_output=MAX_SEARCH_OUTPUT)
        found, more = rules.matches_of(result.stdout, call_input.limit, MAX_MATCH_TEXT)
        if result.exit_code not in (0, 1) and not found:
            # Two: a pattern grep cannot read, or a path that is not there.
            said = result.stderr.strip()[:500] or f"the search ended with {result.exit_code}"
            raise ToolFailed(ToolFailure.PERMANENT, said)
        return Matches(
            matches=tuple(Match(path=p, line=n, text=t) for p, n, t in found),
            more=more or result.truncated,
        )


class CommandInput(ToolInput):
    argv: tuple[str, ...] = Field(min_length=1)


class CommandOutput(Platform):
    exit_code: int | None
    stdout: str
    stderr: str


class RunCommandImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.RUN_COMMAND,
        description=(
            "Runs one command in the workspace, as an argument vector, and answers its exit "
            "code and what it printed."
        ),
        input_model=CommandInput,
        output_model=CommandOutput,
        timeout=timedelta(minutes=10),
        authorization_class=ToolClass.EXECUTE,
        effect=Effect.UNSAFE,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, CommandInput)
        result = await runtime.run(call_input.argv)
        return CommandOutput(exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr)


# The result.


class ResultInput(ToolInput):
    claim: Claim
    evidence: tuple[UUID, ...] = ()


class SubmitResultImpl(NativeToolImpl):
    """A delivery kind's result tool. The loop judges what is submitted
    through the result gate, so the tool itself never runs."""

    SPEC = ToolSpec(
        name=kinds.SUBMIT_RESULT,
        description=(
            "Submits the result: succeeded or failed, with the ids of the runs that show "
            "it, the ones validate answered. The gate judges them: a success counts only "
            "when the validation at your committed head passed."
        ),
        input_model=ResultInput,
        output_model=Text,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        raise ToolFailed(ToolFailure.PERMANENT, "a result is judged by the loop, never run")


class ValidateInput(ToolInput):
    baseline: bool = False


class Validated(Platform):
    """The validations it kept, one per environment the checks name, and
    every run they wrote."""

    validations: tuple[UUID, ...]
    version: str
    runs: tuple[UUID, ...]


class ValidateImpl(NativeToolImpl):
    """Asks the evidence namespace to run the project's checks on a fresh
    executor: at the base for a baseline, or at the committed head. It
    answers the runs the executor wrote, which a result cites; the result
    gate, never this tool, decides whether they pass."""

    SPEC = ToolSpec(
        name=kinds.VALIDATE,
        description=(
            "Runs the project's checks on a fresh executor, apart from your workspace: at "
            "your committed head, or at the base with baseline set. Answers the ids of the "
            "runs it wrote, which submit_result cites. Commit, and open your pull request "
            "first: validation runs at the head on your branch, and a tree that holds work "
            "the branch does not is refused."
        ),
        input_model=ValidateInput,
        output_model=Validated,
        timeout=timedelta(minutes=30),
        authorization_class=ToolClass.EXECUTE,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(self, evidence: Callable[[], EvidenceManagerInterface]) -> None:
        self._evidence = evidence

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, ValidateInput)
        purpose = RunPurpose.BASELINE if call_input.baseline else RunPurpose.VALIDATION
        kept = await self._evidence().validate(ctx, runtime.session_id, purpose)
        return Validated(
            validations=tuple(validation.id for validation in kept),
            version=kept[0].version,
            runs=tuple(run for validation in kept for run in validation.records),
        )


# The repository.

MAX_PULL_REQUEST_TITLE = 200
MAX_PULL_REQUEST_BODY = 20_000


class PullRequestInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_PULL_REQUEST_TITLE)
    body: str = Field(default="", max_length=MAX_PULL_REQUEST_BODY)


class PullRequestOpened(Platform):
    id: str
    url: str
    branch: str
    head: str


class OpenPullRequestImpl(NativeToolImpl):
    """Points the session's own branch at the workspace's committed head and
    opens its pull request on the repository its project binds. The model
    writes the title and the body alone: the branch, the repository, and the
    base are the platform's records, and the head is the checkout's, read as
    a commit's full id or refused. The push token is minted for this call,
    checked before each write, and never reaches the model, the workspace,
    or the answer. The platform's account pushes for every session, so the
    head is recorded as the session's act and the branch bound to it before
    the push, and the pull request once it opens: a comment, a check, or a
    person's push on either finds the session, and an automation it feeds
    knows its cause."""

    SPEC = ToolSpec(
        name=kinds.OPEN_PULL_REQUEST,
        description=(
            "Opens the pull request of your committed head on your session's own branch of "
            "the project's repository, with a title and a body; answers where a person reads "
            "it. Commit first: only the committed head is opened. Opening it again moves the "
            "branch forward to your new head, and keeps the one pull request. The branch only "
            "moves forward: a fix is a new commit on top, never an amend or a rebase."
        ),
        input_model=PullRequestInput,
        output_model=PullRequestOpened,
        timeout=timedelta(minutes=2),
        authorization_class=ToolClass.INTEGRATION,
        effect=Effect.IDEMPOTENT,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        workspaces: Callable[[], WorkspacesManagerInterface],
        intake: Callable[[], IntakeManagerInterface],
    ) -> None:
        self._workspaces = workspaces
        self._intake = intake

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        # Only the session's own branch and its pull request on its bound
        # repository: its work product, never an outward write.
        return Target(attributes={"outward": False})

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PullRequestInput)
        found = await runtime.run(("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"))
        head = found.stdout.strip()
        if found.exit_code != 0 or not COMMIT.fullmatch(head):
            raise ToolFailed(ToolFailure.PERMANENT, "the workspace holds no commit: commit first")
        workspaces = self._workspaces()
        try:
            intake = self._intake()
            token = await workspaces.mint_push_token(ctx, runtime.session_id)
            # Recorded and bound before the push: the forge's events on the
            # commit and the branch may come back before the push answers.
            await intake.record_act(ctx, runtime.session_id, FORGE, (head,))
            await intake.bind_work(ctx, runtime.session_id, HandleKind.BRANCH, token.branch)
            opened = await workspaces.open_pull_request(
                ctx,
                runtime.session_id,
                token.token.get_secret_value(),
                head,
                call_input.title,
                call_input.body,
            )
            await intake.bind_work(ctx, runtime.session_id, HandleKind.PULL_REQUEST, opened.id)
        except Unavailable as failed:
            raise ToolFailed(ToolFailure.TRANSIENT, failed.message) from None
        except (NotFound, NotAuthorized, ValidationFailed, Conflict) as failed:
            raise ToolFailed(ToolFailure.PERMANENT, failed.message) from None
        return PullRequestOpened(id=opened.id, url=opened.url, branch=token.branch, head=head)


# Knowledge.

EXCERPT = 500  # characters of an entry or a passage a search answers

PROJECT, TENANT, PLATFORM = "project", "tenant", "platform"
"""Where a piece of knowledge comes from: an entry of the session's project,
one of its whole tenant, or the platform's own documentation."""


def scope_of(entry: Knowledge) -> str:
    return TENANT if entry.project_id is None else PROJECT


class KnowledgeQuery(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class KnowledgeHit(Platform):
    scope: str
    slug: str | None  # what read_knowledge takes
    title: str
    heading: str | None = None  # the section of a platform document
    excerpt: str


class KnowledgeHits(Platform):
    hits: tuple[KnowledgeHit, ...]


class SearchKnowledgeImpl(NativeToolImpl):
    """Searches what the session may know: the reviewed entries of its
    project and of its whole tenant, never another project's or another
    tenant's, and the platform's own documentation. An entry waiting for its
    review is never found. The session and its project are the call's,
    never the input's."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_KNOWLEDGE,
        description=(
            "Searches the knowledge base: the entries people of your team kept for your "
            "project and for the whole team, and the platform's documentation. Answers at "
            "most limit of each, best first, each with its scope, its slug, its title, and "
            "its opening. Read one whole with read_knowledge and its slug."
        ),
        input_model=KnowledgeQuery,
        output_model=KnowledgeHits,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, corpus: Corpus, knowledge: Callable[[], KnowledgeManagerInterface]) -> None:
        self._corpus = corpus
        self._knowledge = knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, KnowledgeQuery)
        entries = await self._knowledge().search(
            ctx, runtime.session_id, call_input.query, call_input.limit
        )
        passages = rules.search(self._corpus, call_input.query, call_input.limit)
        hits = [
            KnowledgeHit(
                scope=scope_of(entry),
                slug=entry.slug,
                title=entry.title,
                excerpt=entry.text[:EXCERPT],
            )
            for entry in entries
        ]
        hits += [
            KnowledgeHit(
                scope=PLATFORM,
                slug=passage.path,
                title=passage.title,
                heading=passage.heading,
                excerpt=passage.text[:EXCERPT],
            )
            for passage in passages
        ]
        return KnowledgeHits(hits=tuple(hits))


class KnowledgeSlug(ToolInput):
    slug: str = Field(min_length=1, max_length=MAX_PATH)


class KnowledgeRead(Platform):
    scope: str
    slug: str
    title: str
    text: str


class ReadKnowledgeImpl(NativeToolImpl):
    """Reads one piece of knowledge whole, by the slug a search answered: a
    document of the platform's corpus by its path, or a reviewed entry the
    session reaches. Any other entry is not found, as one that never existed
    is not."""

    SPEC = ToolSpec(
        name=kinds.READ_KNOWLEDGE,
        description=(
            "Reads one piece of the knowledge base whole, by the slug search_knowledge answered."
        ),
        input_model=KnowledgeSlug,
        output_model=KnowledgeRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, corpus: Corpus, knowledge: Callable[[], KnowledgeManagerInterface]) -> None:
        self._corpus = corpus
        self._knowledge = knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, KnowledgeSlug)
        slug = call_input.slug
        for document in self._corpus.documents:
            if document.path == slug:
                return KnowledgeRead(
                    scope=PLATFORM, slug=slug, title=document.title, text=document.text
                )
        entry = await self._knowledge().read(ctx, runtime.session_id, slug)
        return KnowledgeRead(scope=scope_of(entry), slug=slug, title=entry.title, text=entry.text)


class SuggestionInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_NAME)
    trigger: tuple[str, ...] = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Suggested(Platform):
    slug: str | None
    note: str


class SuggestKnowledgeImpl(NativeToolImpl):
    """Suggests an entry for the session's project, or its whole tenant when
    it has none. It waits for a person's review, and no session recalls,
    finds, or reads it before. A repeat would suggest it twice, so a call
    whose run was lost is never run again."""

    SPEC = ToolSpec(
        name=kinds.SUGGEST_KNOWLEDGE,
        description=(
            "Suggests an entry for the knowledge base: what a later session should not have "
            "to find out again, such as a procedure, a pitfall, or how a tool behaves here. "
            "Give it a title, the words that should bring it into a session that is about "
            "them, and its text. A person reviews it before any session reads it."
        ),
        input_model=SuggestionInput,
        output_model=Suggested,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.WRITE,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(self, knowledge: Callable[[], KnowledgeManagerInterface]) -> None:
        self._knowledge = knowledge

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SuggestionInput)
        entry = await self._knowledge().suggest(
            ctx, runtime.session_id, call_input.title, call_input.trigger, call_input.text
        )
        return Suggested(slug=entry.slug, note="It waits for a person's review.")


# The assistant's.


class SearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class Found(Platform):
    passages: tuple[Passage, ...]


class SearchCorpusImpl(NativeToolImpl):
    """Searches the corpus the root was given: what the knowledge map lists
    for the tenant's users, and nothing else."""

    SPEC = ToolSpec(
        name=kinds.SEARCH_CORPUS,
        description=(
            "Searches the product's documentation for the passages that answer a question. "
            "Each passage names the document and the heading it comes from: cite them."
        ),
        input_model=SearchInput,
        output_model=Found,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, corpus: Corpus) -> None:
        self._corpus = corpus

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SearchInput)
        return Found(passages=rules.search(self._corpus, call_input.query, call_input.limit))


# The assistant's readers. Each reads through the asking person's own
# permissions: the call's context is theirs, so a row of another tenant's,
# or one marked deleted, is not found, as one that never existed is not. Each
# answers a record's shape, never a session's content, and bounds its list.

LIST_MAX = 50  # rows one list answers at most
SESSION_SCAN = 100
"""The sessions one list_sessions call reads at most, newest first, before
it filters by park reason and project: the call stays one read of a page and
at most that many lookups of a project, and its answer says where to read
on."""
RUNS_MAX = 20  # an automation's recent runs one read answers at most
HOSTS_MAX = 20  # a pool's hosts read_wait answers at most
CHILDREN_MAX = 20  # the sub-agents read_session answers at most
HISTORY_PAGE = 200  # steps one read of a history takes


class SessionInput(ToolInput):
    session_id: UUID


class HeldCall(Platform):
    """A call the session holds for a person's decision: the tool, its
    class, and the roles the tenant's policy lets decide that class."""

    seq: int
    tool: str
    authorization_class: str
    requested_at: datetime
    decided_by: tuple[Role, ...]


class ChildLine(Platform):
    session_id: UUID
    kind: str
    status: SessionStatus


class SessionState(Platform):
    """Where a session stands, as its record says: never its content."""

    kind: str
    kind_version: int
    title: str
    started_by: UUID
    project_id: UUID | None = None
    parent_id: UUID | None = None
    handed_off_from: UUID | None = None
    status: SessionStatus
    waiting_input: bool  # a message that woke it has not reached the model yet
    park_reason: ParkReason | None = None
    unlock: str | None = None  # what clears the park: an approval, a budget's id, a job
    retry_at: datetime | None = None
    held_calls: tuple[HeldCall, ...] = ()  # when it waits on an approval
    children: tuple[ChildLine, ...] = ()  # when it waits on its sub-agents
    archived: bool


async def history_of(
    steps: StepsManagerInterface, ctx: TenantContext, session_id: UUID
) -> list[Step]:
    """A session's whole history, in order, a page at a time. Read after the
    session itself, so another tenant's is never reached."""
    history: list[Step] = []
    while True:
        after = history[-1].seq if history else 0
        page = await steps.get_steps(ctx, session_id, after, HISTORY_PAGE)
        history.extend(page.items)
        if not page.has_more or not page.items:
            return history


class ReadSessionImpl(NativeToolImpl):
    """Reads one session of the tenant: its record, and what its park waits
    on. A park on an approval answers each call it holds and who may decide
    it; a park on its sub-agents answers them."""

    SPEC = ToolSpec(
        name=kinds.READ_SESSION,
        description=(
            "Reads where a session of the tenant stands: its kind, title, project, who "
            "started it, whether it is pending, running, parked, or idle, why it is parked "
            "and what clears it, and when it tries again. A session parked on an approval "
            "answers each call it holds and the roles that may decide it; one parked on its "
            "sub-agents answers them."
        ),
        input_model=SessionInput,
        output_model=SessionState,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        steps: Callable[[], StepsManagerInterface],
        policies: Callable[[], ToolsManagerInterface],
        projects: Callable[[], ProjectsManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._steps = steps
        self._policies = policies
        self._projects = projects

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SessionInput)
        session = await self._sessions().get_session(ctx, call_input.session_id)
        park = session.park
        project = await self._projects().project_of(ctx, session.id)
        held: tuple[HeldCall, ...] = ()
        if park is not None and park.reason is ParkReason.PERSON and park.unlock == APPROVAL_UNLOCK:
            policy = await self._policies().get_policy(ctx)
            held = tuple(
                held_call(request, approver_roles(policy, request.header.authorization_class))
                for request in held_calls(await history_of(self._steps(), ctx, session.id))
                if isinstance(request.header, ToolRequestHeader)
            )
        children: tuple[ChildLine, ...] = ()
        if park is not None and park.reason is ParkReason.CHILDREN:
            page = await self._sessions().get_children(ctx, session.id, None, CHILDREN_MAX)
            children = tuple(
                ChildLine(session_id=child.id, kind=child.kind, status=child.status)
                for child in page.items
            )
        return SessionState(
            kind=session.kind,
            kind_version=session.kind_version,
            title=session.title,
            started_by=session.created_by,
            project_id=None if project is None else project.id,
            parent_id=session.parent_id,
            handed_off_from=session.handed_off_from,
            status=session.status,
            waiting_input=session.pending_input is not None,
            park_reason=None if park is None else park.reason,
            unlock=None if park is None else park.unlock,
            retry_at=None if park is None else park.retry_at,
            held_calls=held,
            children=children,
            archived=session.archived_at is not None,
        )


def held_call(request: Step, roles: tuple[Role, ...]) -> HeldCall:
    header = request.header
    assert isinstance(header, ToolRequestHeader)
    return HeldCall(
        seq=request.seq,
        tool=header.tool,
        authorization_class=header.authorization_class,
        requested_at=request.created_at,
        decided_by=roles,
    )


class SessionsQuery(ToolInput):
    status: SessionStatus | None = None
    park_reason: ParkReason | None = None
    project_id: UUID | None = None
    before: UUID | None = None  # the `next` an earlier answer gave
    limit: int = Field(default=20, ge=1, le=LIST_MAX)

    @model_validator(mode="after")
    def _a_park_reason_lists_parked_sessions(self) -> Self:
        if self.park_reason is not None and self.status not in (None, SessionStatus.PARKED):
            raise ValueError("a park reason lists parked sessions: leave status out")
        return self


class SessionLine(Platform):
    session_id: UUID
    title: str
    kind: str
    status: SessionStatus
    park_reason: ParkReason | None = None
    started_by: UUID
    created_at: datetime


class SessionList(Platform):
    sessions: tuple[SessionLine, ...]
    next: UUID | None  # pass it as `before` to read on; none once the list is read


class ListSessionsImpl(NativeToolImpl):
    """Lists the tenant's sessions, newest first, by status, park reason, and
    project. One call reads at most a scan's worth of sessions, so a filter
    that matches few may answer fewer than its limit with a `next`."""

    SPEC = ToolSpec(
        name=kinds.LIST_SESSIONS,
        description=(
            "Lists the tenant's sessions, newest first: each one's id, title, kind, "
            "status, park reason, who started it, and when. Filter by status, by park reason "
            "(parked sessions only), or by project. When the answer carries next, pass it as "
            "before to read on: a filter that matches few may answer fewer than limit."
        ),
        input_model=SessionsQuery,
        output_model=SessionList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        projects: Callable[[], ProjectsManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._projects = projects

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SessionsQuery)
        reason, project_id = call_input.park_reason, call_input.project_id
        status = SessionStatus.PARKED if reason is not None else call_input.status
        page = await self._sessions().get_sessions(ctx, status, call_input.before, SESSION_SCAN)
        found: list[SessionLine] = []
        for session in page.items:
            if reason is not None and (session.park is None or session.park.reason is not reason):
                continue
            if project_id is not None:
                project = await self._projects().project_of(ctx, session.id)
                if project is None or project.id != project_id:
                    continue
            found.append(
                SessionLine(
                    session_id=session.id,
                    title=session.title,
                    kind=session.kind,
                    status=session.status,
                    park_reason=None if session.park is None else session.park.reason,
                    started_by=session.created_by,
                    created_at=session.created_at,
                )
            )
            if len(found) == call_input.limit:
                more = session.id != page.items[-1].id or page.has_more
                return SessionList(sessions=tuple(found), next=session.id if more else None)
        last = page.items[-1].id if page.items and page.has_more else None
        return SessionList(sessions=tuple(found), next=last)


class WaitingItem(Platform):
    """The session's loop on the work queue: the item made last for it."""

    status: WorkStatus
    lane: str
    queued_at: datetime
    available_at: datetime
    attempts: int
    max_attempts: int
    lease_expires_at: datetime | None = None
    running_ahead: int | None = None  # the tenant's loops running ahead of it, while queued


class PoolHost(Platform):
    host_id: UUID
    name: str
    online: bool
    last_seen_at: datetime


class SessionWait(Platform):
    """What a session waits on outside its own history: its loop's place on
    the work queue, and where it runs, with the hosts that may take it."""

    session_id: UUID
    status: SessionStatus
    park_reason: ParkReason | None = None
    retry_at: datetime | None = None
    loop: WaitingItem | None = None
    runs_in: str  # "cloud", or the pool it is pinned to
    pool_id: UUID | None = None
    hosts_online: int = 0
    hosts: tuple[PoolHost, ...] = ()  # the pool's, the one seen last first
    workspace_host: PoolHost | None = None  # the host that holds its workspace
    waits_for_a_host: bool  # no host of its pool online, or its workspace's host offline


CLOUD = "cloud"


class ReadWaitImpl(NativeToolImpl):
    """Reads what a session waits on beyond its park: its loop's item on the
    work queue, the tenant's own loops running ahead of it, and where it runs,
    the cloud or a pool of the tenant's hosts and which of them are online,
    and the host that holds its workspace, which it waits for while that
    host is offline."""

    SPEC = ToolSpec(
        name=kinds.READ_WAIT,
        description=(
            "Reads what a pending or slow session waits on: its loop's item on the work "
            "queue (queued or running, its lane, since when, its attempts, and how many of "
            "the tenant's loops run ahead of it), and where it runs: the cloud, or the "
            "tenant's pool it is pinned to, with the pool's hosts and which are online. A "
            "pinned session with no host online waits for one. A workspace lives on the host "
            "that prepared it: while that host is offline, the session waits for it, even "
            "with other hosts online, and its last_seen_at says since when."
        ),
        input_model=SessionInput,
        output_model=SessionWait,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        work: Callable[[], WorkManagerInterface],
        hosts: Callable[[], HostsManagerInterface],
        relay: Callable[[], RelayManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._work = work
        self._hosts = hosts
        self._relay = relay

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SessionInput)
        session = await self._sessions().get_session(ctx, call_input.session_id)
        item = await self._work().latest_for_target(ctx, WorkKind.LOOP, session.id)
        loop: WaitingItem | None = None
        if item is not None:
            queued = item.status is WorkStatus.QUEUED
            loop = WaitingItem(
                status=item.status,
                lane=item.lane,
                queued_at=item.created_at,
                available_at=item.available_at,
                attempts=item.attempts,
                max_attempts=item.max_attempts,
                lease_expires_at=item.lease_expires_at,
                running_ahead=await self._work().claimed_ahead(ctx, item) if queued else None,
            )
        placement = await self._hosts().placement_of(ctx, session.id)
        pool = placement.pool
        hosts: tuple[PoolHost, ...] = ()
        holder: HostStatus | None = None
        if pool is not None:
            hosts = tuple(
                _pool_host(status)
                for status in (await self._hosts().get_hosts(ctx, pool.id))[:HOSTS_MAX]
            )
            binding = await self._relay().binding_of(ctx, session.id)
            if binding is not None:
                holder = await self._hosts().get_host(ctx, pool.id, binding.host_id)
                # A revoked host took the workspace with it: another host of
                # the pool prepares one, so nothing pins the session to it.
                if holder is not None and holder.host.revoked_at is not None:
                    holder = None
        park = session.park
        return SessionWait(
            session_id=session.id,
            status=session.status,
            park_reason=None if park is None else park.reason,
            retry_at=None if park is None else park.retry_at,
            loop=loop,
            runs_in=CLOUD if pool is None else pool.name,
            pool_id=None if pool is None else pool.id,
            hosts_online=placement.hosts_online,
            hosts=hosts,
            workspace_host=None if holder is None else _pool_host(holder),
            waits_for_a_host=placement.waiting or (holder is not None and not holder.online),
        )


def _pool_host(status: HostStatus) -> PoolHost:
    return PoolHost(
        host_id=status.host.id,
        name=status.host.name,
        online=status.online,
        last_seen_at=status.host.last_seen_at,
    )


class PageInput(ToolInput):
    after: UUID | None = None  # the `next` an earlier answer gave
    limit: int = Field(default=20, ge=1, le=LIST_MAX)


class ProjectInput(ToolInput):
    project_id: UUID


class ProjectRead(Platform):
    project_id: UUID
    name: str
    repository: str  # its host and path, such as github.com/octo/reports
    created_at: datetime
    created_by: UUID


class ProjectList(Platform):
    projects: tuple[ProjectRead, ...]
    next: UUID | None  # pass it as `after` to read on; none once the list is read


def project_read(project: Project) -> ProjectRead:
    return ProjectRead(
        project_id=project.id,
        name=project.name,
        repository=f"{project.repository.host}/{project.repository.path}",
        created_at=project.created_at,
        created_by=project.created_by,
    )


class ListProjectsImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_PROJECTS,
        description=(
            "Lists the tenant's projects: each one's id, name, and the repository its work "
            "lands on. When the answer carries next, pass it as after to read on."
        ),
        input_model=PageInput,
        output_model=ProjectList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, projects: Callable[[], ProjectsManagerInterface]) -> None:
        self._projects = projects

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PageInput)
        limit = call_input.limit
        rows = await self._projects().list_projects(ctx, call_input.after, limit + 1)
        shown = rows[:limit]
        more = len(rows) > limit
        return ProjectList(
            projects=tuple(project_read(p) for p in shown),
            next=shown[-1].id if more else None,
        )


class ReadProjectImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.READ_PROJECT,
        description=(
            "Reads one project of the tenant: its name, the repository its work lands on, "
            "and who made it when. Its sessions are list_sessions with its project_id."
        ),
        input_model=ProjectInput,
        output_model=ProjectRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, projects: Callable[[], ProjectsManagerInterface]) -> None:
        self._projects = projects

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, ProjectInput)
        return project_read(await self._projects().get_project(ctx, call_input.project_id))


class AutomationLine(Platform):
    automation_id: UUID
    name: str
    trigger: str  # an event or a schedule
    action: str
    enabled: bool
    runs_as: str


class AutomationList(Platform):
    automations: tuple[AutomationLine, ...]
    next: UUID | None  # pass it as `after` to read on; none once the list is read


class AutomationInput(ToolInput):
    automation_id: UUID
    runs: int = Field(default=5, ge=1, le=RUNS_MAX)


class RunLine(Platform):
    """One firing of an automation, as recorded: started, queued, or refused
    and why, the session it started or messaged, and how it ended."""

    run_id: UUID
    fired_at: datetime
    status: str
    refusal: str | None = None
    hop: int
    session_id: UUID | None = None
    opened: bool
    outcome: str | None = None
    started_at: datetime | None = None
    closed_at: datetime | None = None


class AutomationRead(Platform):
    """An automation's shape and its recent runs: never the text a person
    briefed it with or an event brought."""

    automation_id: UUID
    name: str
    enabled: bool
    runs_as: str
    own_events: bool
    trigger: str
    integrations: tuple[str, ...]
    arrivals: tuple[str, ...]
    effects: tuple[str, ...]
    every: timedelta | None = None
    action: str
    agent_kind: str | None = None
    project_id: UUID | None = None
    session_id: UUID | None = None
    limits: AutomationLimits
    runs: tuple[RunLine, ...]  # newest first


def automation_line(automation: Automation) -> AutomationLine:
    return AutomationLine(
        automation_id=automation.id,
        name=automation.name,
        trigger=automation.trigger.kind,
        action=automation.action.kind,
        enabled=automation.enabled,
        runs_as=automation.runs_as,
    )


class ListAutomationsImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_AUTOMATIONS,
        description=(
            "Lists the tenant's automations: each one's id, name, whether an event or a "
            "schedule fires it, what it does, whether it is on, and whom it runs as. When "
            "the answer carries next, pass it as after to read on."
        ),
        input_model=PageInput,
        output_model=AutomationList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, automations: Callable[[], AutomationsManagerInterface]) -> None:
        self._automations = automations

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, PageInput)
        limit = call_input.limit
        rows = await self._automations().list_automations(ctx, call_input.after, limit + 1)
        shown = rows[:limit]
        return AutomationList(
            automations=tuple(automation_line(a) for a in shown),
            next=shown[-1].id if len(rows) > limit else None,
        )


class ReadAutomationImpl(NativeToolImpl):
    """Reads one automation of the tenant and its recent runs. The automation
    is read first, so another tenant's is not found before any run is."""

    SPEC = ToolSpec(
        name=kinds.READ_AUTOMATION,
        description=(
            "Reads one automation of the tenant: what fires it, what it does, its limits "
            "(cost cap, rate, concurrency, queue, hop limit), whom it runs as, and its "
            "recent runs, newest first: each started, queued, or refused and why, the "
            "session it started or messaged, and how it ended."
        ),
        input_model=AutomationInput,
        output_model=AutomationRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, automations: Callable[[], AutomationsManagerInterface]) -> None:
        self._automations = automations

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, AutomationInput)
        automation = await self._automations().get_automation(ctx, call_input.automation_id)
        runs = await self._automations().get_runs(ctx, automation.id, call_input.runs)
        trigger, action = automation.trigger, automation.action
        return AutomationRead(
            automation_id=automation.id,
            name=automation.name,
            enabled=automation.enabled,
            runs_as=automation.runs_as,
            own_events=automation.own_events,
            trigger=trigger.kind,
            integrations=trigger.integrations,
            arrivals=trigger.arrivals,
            effects=trigger.effects,
            every=trigger.every,
            action=action.kind,
            agent_kind=action.agent_kind,
            project_id=action.project_id,
            session_id=action.session_id,
            limits=automation.limits,
            runs=tuple(
                RunLine(
                    run_id=run.id,
                    fired_at=run.created_at,
                    status=run.status,
                    refusal=run.refusal,
                    hop=run.hop,
                    session_id=run.session_id,
                    opened=run.opened,
                    outcome=run.outcome,
                    started_at=run.started_at,
                    closed_at=run.closed_at,
                )
                for run in runs[: call_input.runs]
            ),
        )


class DraftInput(ToolInput):
    rules: tuple[PolicyRule, ...] = ()
    approvers: tuple[ApproverRule, ...] = ()


class DraftToolPolicyImpl(NativeToolImpl):
    """Drafts the tenant's tool policy and shows the difference from what is
    live. It reads the live policy and writes nothing: a person applies the
    draft by writing the policy it holds, at the version it names."""

    SPEC = ToolSpec(
        name=kinds.DRAFT_TOOL_POLICY,
        description=(
            "Drafts the tenant's tool policy, whole: its rules and who approves each class "
            "of call. Answers the draft checked against what the tenant holds, and the "
            "rules it adds and removes from the live policy. It changes nothing: show the "
            "difference to the person, who applies it."
        ),
        input_model=DraftInput,
        output_model=PolicyDraft,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        policies: Callable[[], ToolsManagerInterface],
        tools: frozenset[str],
        classes: frozenset[str],
    ) -> None:
        self._policies = policies
        self._tools = tools
        self._classes = classes

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, DraftInput)
        live = await self._policies().get_policy(ctx)
        return rules.draft_policy(
            live, call_input.rules, call_input.approvers, self._tools, self._classes
        )


class HandOffInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    objective: str = Field(min_length=1, max_length=20_000)


class HandedOff(Platform):
    session_id: UUID
    note: str


class HandOffToEngineerImpl(NativeToolImpl):
    """Hands engineering work to a new engineer session. Its objective is
    data there, it waits for its person to confirm it, and the session that
    handed it over cannot steer it. The new session's id is the call's own,
    so a call asked again finds the session it made."""

    SPEC = ToolSpec(
        name=kinds.HAND_OFF,
        description=(
            "Hands engineering work to a new engineer session, with a title and an objective "
            "that stands on its own: what to change, why, and how to know it is done. The "
            "session starts when its person confirms it; you cannot steer it after."
        ),
        input_model=HandOffInput,
        output_model=HandedOff,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.SPAWN,
        effect=Effect.IDEMPOTENT,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agents: Callable[[], AgentsManagerInterface]) -> None:
        self._agents = agents

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, HandOffInput)
        handoff = Handoff(
            id=runtime.key,
            kind=kinds.ENGINEER,
            title=call_input.title,
            objective=call_input.objective,
        )
        session = await self._agents().hand_off(ctx, runtime.session_id, handoff)
        return HandedOff(
            session_id=session.id, note="It starts when its person confirms the objective."
        )
