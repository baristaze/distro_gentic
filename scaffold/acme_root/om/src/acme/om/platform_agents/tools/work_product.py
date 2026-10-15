"""The `work_product` toolset: validate a change on a fresh executor, open
its pull request on the session's own branch, and submit the result the
gate judges. The push token is minted for the call and checked before it
writes; the model names neither the branch nor the repository, and never
sees the token."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from pydantic import Field

from acme.om.agent_steps.types.header import ToolFailure
from acme.om.agent_workspaces import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces.rules import COMMIT
from acme.om.base import OmBase
from acme.om.context import TenantContext
from acme.om.evidence import EvidenceManagerInterface
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
from acme.om.platform_agents import kinds
from acme.om.platform_agents.tools.base import NativeToolImpl, ResultInput, Text
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.policy import Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec


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

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        raise ToolFailed(ToolFailure.PERMANENT, "a result is judged by the loop, never run")


class ValidateInput(ToolInput):
    baseline: bool = False


class Validated(OmBase):
    """The validations it kept, one per executor the checks name, and
    every run they wrote."""

    validations: tuple[UUID, ...]
    version: str
    runs: tuple[UUID, ...]


class ValidateImpl(NativeToolImpl):
    """Asks the evidence namespace to run the agent project's checks on a fresh
    executor: at the base for a baseline, or at the committed head. It
    answers the runs the executor wrote, which a result cites; the result
    gate, never this tool, decides whether they pass."""

    SPEC = ToolSpec(
        name=kinds.VALIDATE,
        description=(
            "Runs the agent project's checks on a fresh executor, apart from your workspace: at "
            "your committed head, or at the base with baseline set. Answers the ids of the "
            "runs it wrote, which submit_result cites. Take a baseline before you validate a "
            "change, and again whenever your base moves, as when your branch takes the default "
            "branch in or is cut again: a success counts only when a baseline at its base ran "
            "before its head was validated. Commit, and open your pull request first: "
            "validation runs at the head on your branch, and a tree that holds work the branch "
            "does not is refused."
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

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, ValidateInput)
        purpose = RunPurpose.BASELINE if call_input.baseline else RunPurpose.VALIDATION
        kept = await self._evidence().validate(ctx, runtime.agent_session_id, purpose)
        return Validated(
            validations=tuple(validation.id for validation in kept),
            version=kept[0].version,
            runs=tuple(run for validation in kept for run in validation.records),
        )


MAX_PULL_REQUEST_TITLE = 200
MAX_PULL_REQUEST_BODY = 20_000


class PullRequestInput(ToolInput):
    title: str = Field(min_length=1, max_length=MAX_PULL_REQUEST_TITLE)
    body: str = Field(default="", max_length=MAX_PULL_REQUEST_BODY)


class PullRequestOpened(OmBase):
    id: str
    url: str
    branch: str
    head: str


class OpenPullRequestImpl(NativeToolImpl):
    """Points the session's own branch at the workspace's committed head and
    opens its pull request on the repository its agent project binds. The model
    writes the title and the body alone: the branch, the repository, and the
    base are the platform's records, and the head is the checkout's, read as
    a commit's full id or refused. The push token is minted for this call,
    checked before each write, and never reaches the model, the workspace,
    or the answer. The platform's account pushes for every session, so the
    head is recorded as the session's act and the branch bound to it before
    the push, and the pull request once it opens: a comment, a check, or a
    person's push on either finds the session, and an agent automation it feeds
    knows its cause."""

    SPEC = ToolSpec(
        name=kinds.OPEN_PULL_REQUEST,
        description=(
            "Opens the pull request of your committed head on your session's own branch of "
            "the agent project's repository, with a title and a body; answers where a person reads "
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
        agent_workspaces: Callable[[], AgentWorkspacesManagerInterface],
        intake: Callable[[], IntakeManagerInterface],
    ) -> None:
        self._agent_workspaces = agent_workspaces
        self._intake = intake

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        # Only the session's own branch and its pull request on its bound
        # repository: its work product, never an outward write.
        return Target(attributes={"outward": False})

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, PullRequestInput)
        found = await runtime.run(("git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"))
        head = found.stdout.strip()
        if found.exit_code != 0 or not COMMIT.fullmatch(head):
            raise ToolFailed(ToolFailure.PERMANENT, "the workspace holds no commit: commit first")
        agent_workspaces = self._agent_workspaces()
        try:
            intake = self._intake()
            token = await agent_workspaces.mint_push_token(ctx, runtime.agent_session_id)
            # Recorded and bound before the push: the forge's events on the
            # commit and the branch may come back before the push answers.
            await intake.record_act(ctx, runtime.agent_session_id, FORGE, (head,))
            await intake.bind_work(ctx, runtime.agent_session_id, HandleKind.BRANCH, token.branch)
            opened = await agent_workspaces.open_pull_request(
                ctx,
                runtime.agent_session_id,
                token.token.get_secret_value(),
                head,
                call_input.title,
                call_input.body,
            )
            await intake.bind_work(
                ctx, runtime.agent_session_id, HandleKind.PULL_REQUEST, opened.id
            )
        except Unavailable as failed:
            raise ToolFailed(ToolFailure.TRANSIENT, failed.message) from None
        except (NotFound, NotAuthorized, ValidationFailed, Conflict) as failed:
            raise ToolFailed(ToolFailure.PERMANENT, failed.message) from None
        return PullRequestOpened(id=opened.id, url=opened.url, branch=token.branch, head=head)
