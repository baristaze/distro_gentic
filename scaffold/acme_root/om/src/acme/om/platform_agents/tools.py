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
assistant's read the corpus and live state, and draft; the one that hands
work on starts a session that waits for its person. The knowledge tools
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
from acme.om.agents.types.request import MAX_TITLE, Handoff
from acme.om.agents.types.result import Claim
from acme.om.base import Platform
from acme.om.context import TenantContext
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
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.tools import FORGE
from acme.om.intake.types.link import HandleKind
from acme.om.knowledge import KnowledgeManagerInterface
from acme.om.knowledge.types.knowledge import MAX_TEXT, Knowledge
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.types.corpus import Corpus, Passage
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.steps.types.content import MAX_NAME
from acme.om.steps.types.header import ParkReason, ToolFailure
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import ApproverRule, PolicyRule, Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec
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
    pattern: str = Field(min_length=1, max_length=500, pattern=NO_NUL)
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
    validation_id: UUID
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
        validation = await self._evidence().validate(ctx, runtime.session_id, purpose)
        return Validated(
            validation_id=validation.id, version=validation.version, runs=validation.records
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


class SessionInput(ToolInput):
    session_id: UUID


class SessionState(Platform):
    """Where a session stands, as its record says: never its content."""

    kind: str
    kind_version: int
    status: SessionStatus
    waiting_input: bool  # a message that woke it has not reached the model yet
    park_reason: ParkReason | None = None
    retry_at: datetime | None = None
    archived: bool


class ReadSessionImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.READ_SESSION,
        description=(
            "Reads where a session of the tenant stands: its kind, whether it is pending, "
            "running, parked, or idle, why it is parked and when it tries again."
        ),
        input_model=SessionInput,
        output_model=SessionState,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, sessions: Callable[[], AgentSessionsManagerInterface]) -> None:
        self._sessions = sessions

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, SessionInput)
        session = await self._sessions().get_session(ctx, call_input.session_id)
        park = session.park
        return SessionState(
            kind=session.kind,
            kind_version=session.kind_version,
            status=session.status,
            waiting_input=session.pending_input is not None,
            park_reason=None if park is None else park.reason,
            retry_at=None if park is None else park.retry_at,
            archived=session.archived_at is not None,
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
