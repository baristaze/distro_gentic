"""The tools through which a session acts on the outside as the platform's
one account. Every session acts through that one account, so the account
says nothing of which session acted: each tool records its act with intake
before it acts, under a mark the system carries on what it makes, and then
under the system's own id for it. An event that is or follows from the act
names the session it came from, and an automation it feeds knows its cause
and its hop, so an agent's act cannot start an endless chain.

A tool that reads a manager takes it late, as a callable the root answers
once it has built it."""

from collections.abc import Callable
from datetime import timedelta
from typing import ClassVar

from pydantic import Field

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface
from acme.integrations.exceptions import ProviderRefused
from acme.om.base import Platform
from acme.om.context import TenantContext
from acme.om.exceptions import ToolFailed
from acme.om.intake.manager import IntakeManagerInterface
from acme.om.steps.types.content import MAX_NAME
from acme.om.steps.types.header import ToolFailure
from acme.om.tools.tool import ToolInterface, ToolRuntime
from acme.om.tools.types.policy import Target
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec

COMMENT = "comment"
FORGE = "forge"
"""The integration that holds a session's work: its pull requests and its
tickets."""

MAX_COMMENT = 20_000


class CommentInput(ToolInput):
    on: str = Field(min_length=1, max_length=MAX_NAME)
    text: str = Field(min_length=1, max_length=MAX_COMMENT)


class Commented(Platform):
    id: str


class CommentImpl(ToolInterface):
    """Comments on a pull request or a ticket of the forge, as the platform's
    account, through the installation of the forge that holds its
    repository, and only once the session's own tenant connected it: any
    other is refused before anything is recorded or posted. The act is
    recorded under the call's key before the comment is posted, so an event
    the forge sends before the post answers still names the session; then
    under the forge's id for the comment."""

    SPEC: ClassVar[ToolSpec] = ToolSpec(
        name=COMMENT,
        description=(
            "Comments on a pull request or a ticket of the forge, as the platform's account. "
            "`on` names it, such as owner/repo#12; `text` is the comment."
        ),
        input_model=CommentInput,
        output_model=Commented,
        timeout=timedelta(seconds=30),
        authorization_class=ToolClass.INTEGRATION,
        effect=Effect.UNSAFE,
        interruptible=False,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        intake: Callable[[], IntakeManagerInterface],
        integrations: Callable[[str], IntegrationInterface],
    ) -> None:
        self._intake = intake
        self._integrations = integrations

    @property
    def spec(self) -> ToolSpec:
        return self.SPEC

    async def target(self, ctx: TenantContext, call_input: ToolInput) -> Target:
        # A comment lands on the forge, past the session's own work, and the
        # target names no session to tell its own pull request from another's:
        # every comment acts outward, so the platform's ceiling holds it for a
        # person however a kind's policy allows the class.
        return Target(attributes={"outward": True})

    async def preflight(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> None:
        return None

    async def run(
        self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime
    ) -> Platform:
        assert isinstance(call_input, CommentInput)
        intake = self._intake()
        forge = self._integrations(FORGE)
        mark = str(runtime.key)
        try:
            installation = await forge.installation_of(call_input.on)
        except InfraException as failed:
            raise ToolFailed(
                ToolFailure.PERMANENT
                if isinstance(failed, ProviderRefused)
                else ToolFailure.TRANSIENT,
                f"the forge named no installation of {call_input.on}: {failed.message}",
            ) from None
        if await intake.tenant_of(ctx, FORGE, installation) != ctx.org_id:
            raise ToolFailed(
                ToolFailure.DENIED,
                f"no installation of the forge this tenant connected holds {call_input.on}",
            )
        # Recorded before the act: the forge's event may come back before the
        # post answers.
        await intake.record_act(ctx, runtime.session_id, FORGE, (mark,))
        try:
            posted = await forge.post(
                call_input.on, call_input.text, mark, installation=installation
            )
        except InfraException as failed:
            raise ToolFailed(
                ToolFailure.TRANSIENT, f"the forge took no comment: {failed.message}"
            ) from None
        if posted.id != mark:
            await intake.record_act(ctx, runtime.session_id, FORGE, (posted.id,))
        return Commented(id=posted.id)
