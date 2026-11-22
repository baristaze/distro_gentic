"""The platform's hooks into each run of the engine's loop
(`acme.om.agents.hooks`). What a session holds beyond its kind, a tenant's
own connector say, is answered by the hooks the process wires (`inner`).
Before the run's first model call, a new loop holds its session's pinned
workspace to where the session runs (`PinnedWorkspacesInterface`): one
that can never be held there is the session's workspace refused, and the
loop ends errored, nothing spent or made, its end naming the cause for a
person. A new loop then renews its session's fill set, so a
fill gone since the last loop switches between loops and never inside
one. Once the run's first call that reaches the workspace has
prepared it, and before that call runs, what changed under the model since
its last loop is told as a step: the workspace was prepared over what that
loop left. A run that reaches no workspace tells nothing, and the next run
that reaches it tells it then."""

from collections.abc import Callable, Sequence
from datetime import datetime

from acme.infra.agent_workspaces import AgentWorkspace, IsolationMode, IsolationRefused
from acme.infra.exceptions import InfraException
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.agent_step import Actor, AgentStep, AgentStepType, Origin
from acme.om.agent_steps.types.content import Content, TextBlock
from acme.om.agent_steps.types.header import MarkHeader
from acme.om.agent_workspaces.pinned import PinnedWorkspacesInterface
from acme.om.agents.hooks import AttachedToolsets, LoopHooksInterface, LoopStart
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.language_models.manager import LanguageModelsManagerInterface
from acme.om.tools.rules import ISOLATION_REFUSED

NEVER_HELD = "the session's pinned workspace can never be held where it runs"
"""What a person reads on the end of a loop whose session's pin can never be
held where it runs, followed by the refusal's own cause when it names one.
One that names none is told what the pin may ask beyond its kind
(`UNNAMED`): its message may hold the host's state, and reaches the log
alone."""
UNNAMED = (
    f"{NEVER_HELD}: no host there gives all it asks, "
    "such as its egress allowlist or its workspace base"
)
"""The cause of a refused pin whose refusal names no cause of its own."""


def changed_step(start: LoopStart, text: str, at: datetime) -> AgentStep:
    """The notice that the world under the model changed since its last
    loop, in the words the workspace's provider gave."""
    return AgentStep(
        id=new_id(),
        created_at=at,
        agent_session_id=start.agent_session.id,
        loop_id=start.loop_id,
        type=AgentStepType.ENVIRONMENT_CHANGED,
        actor=Actor.ENGINE,
        origin=Origin.ENGINE,
        header=MarkHeader(),
        content=Content(blocks=(TextBlock(text=text),)),
    )


class PlatformLoopHooksImpl(LoopHooksInterface):
    """`inner` answers what a session holds beyond its kind and the steps a
    layer above the platform appends; `language_models` is the face over the
    models manager every namespace reaches, and `pinned` the tools manager
    that makes each workspace, each read at call time, since the root
    builds them after the loop's hooks are set."""

    def __init__(
        self,
        inner: LoopHooksInterface,
        language_models: Callable[[], LanguageModelsManagerInterface],
        pinned: Callable[[], PinnedWorkspacesInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._language_models = language_models
        self._pinned = pinned
        self._clock = clock

    async def attached_toolsets(
        self, ctx: TenantContext, agent_session: AgentSession
    ) -> AttachedToolsets:
        return await self._inner.attached_toolsets(ctx, agent_session)

    async def before_first_call(self, ctx: TenantContext, start: LoopStart) -> Sequence[AgentStep]:
        if start.new_loop:
            # A pin keeps its kind's level, so a kind of none has none.
            if start.kind.isolation.mode is not IsolationMode.NONE:
                await self._check_pinned(ctx, start)
            # A fill gone since the last loop switches here, between loops,
            # and never inside one. Renewing twice leaves what once left.
            await self._language_models().renew_fill_set(
                ctx, start.agent_session.id, start.epoch, start.loop_id
            )
        return await self._inner.before_first_call(ctx, start)

    async def _check_pinned(self, ctx: TenantContext, start: LoopStart) -> None:
        """The session's pin, held to where the session runs before any model
        call. A loop past its first call answers its open calls when its
        workspace is refused, so only a new loop, which has none, is held
        here."""
        try:
            await self._pinned().check_pinned(ctx, start.agent_session.id, start.kind.isolation)
        except InfraException as refused:
            if refused.code != ISOLATION_REFUSED:
                raise
            # The session's workspace refused for good: the engine ends the
            # loop errored before any model call, its end naming the cause.
            cause = refused.cause if isinstance(refused, IsolationRefused) else None
            raise IsolationRefused(
                f"{NEVER_HELD}: {refused.message}",
                cause=UNNAMED if not cause else f"{NEVER_HELD}: {cause}",
            ) from refused

    async def workspace_prepared(
        self, ctx: TenantContext, start: LoopStart, workspace: AgentWorkspace
    ) -> Sequence[AgentStep]:
        steps = list(await self._inner.workspace_prepared(ctx, start, workspace))
        if workspace.changed is not None:
            steps.append(changed_step(start, workspace.changed, self._clock()))
        return steps
