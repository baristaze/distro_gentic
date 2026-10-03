"""The tools the shipped kinds call. Each declares its class and its effect,
which is all policy reads of it, and takes a typed input that refuses a
field it does not declare: what a model writes is checked before any of it
runs.

The workspace's four reach the world only through the call's runtime, so a
kind with no workspace cannot use one even when it is handed one. The
engineer's pull request opens its own branch on its project's repository
with a push token the platform mints for the call and checks before it
writes; the model names neither the branch nor the repository, and never
sees the token. The branch and the pull request are bound to the session,
and the push recorded as its act, so the events on them find it. The
assistant's read the corpus and live state, and draft; the one that hands
work on starts a session that waits for its person. A tool that reads a
manager takes it late, as a callable the root answers once it has built
it."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar
from uuid import UUID

from pydantic import Field

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
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.types.corpus import Corpus, Passage
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.steps.types.header import ParkReason, ToolFailure
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import ApproverRule, PolicyRule, Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec
from acme.om.workspaces import WorkspacesManagerInterface
from acme.om.workspaces.rules import COMMIT

MAX_PATH = 1024
MAX_READ = 200_000  # bytes one read takes at most


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


class WriteFileImpl(NativeToolImpl):
    """Writes one file of the workspace. A path the policy of the session's
    project protects is refused at the call, before anyone is asked: the
    evidence reads it (`protection`) from the session's project, never from
    the input."""

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

    def __init__(self, evidence: Callable[[], EvidenceManagerInterface]) -> None:
        self._evidence = evidence

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        # The engine asks a tool's target with no session, and the session's
        # project is what protects a path, so the refusal is made here.
        assert isinstance(call_input, WriteInput)
        target = await self._evidence().protection(ctx, runtime.session_id, [call_input.path])
        if target.kind == PATHS and target.attributes.get("protected"):
            raise ToolFailed(
                ToolFailure.DENIED,
                f"{call_input.path} is protected by the project's validation policy: "
                "it is never changed by an agent",
            )

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, WriteInput)
        data = call_input.text.encode()
        await runtime.write_file(call_input.path, data)
        return Written(path=call_input.path, size=len(data))


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
            "runs it wrote, which submit_result cites. Commit first: a dirty tree is refused."
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
            "branch to your new head, and keeps the one pull request."
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
