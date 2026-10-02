"""The tools the shipped kinds call. Each declares its class and its effect,
which is all policy reads of it, and takes a typed input that refuses a
field it does not declare: what a model writes is checked before any of it
runs.

The workspace's four reach the world only through the call's runtime, so a
kind with no workspace cannot use one even when it is handed one. The
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
from acme.om.exceptions import ToolFailed
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.types.corpus import Corpus, Passage
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.steps.types.header import ParkReason, ToolFailure
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import ApproverRule, PolicyRule, Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

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
            "Submits the result: succeeded or failed, with the ids of the tool responses "
            "that show it. A success with no evidence is refused."
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
