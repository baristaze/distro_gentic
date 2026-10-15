"""The platform's hooks into each run of the engine's loop
(`acme.om.agents.hooks`). What a session holds beyond its kind, a tenant's
own connector say, is answered by the hooks the process wires (`inner`).
Before the run's first model call, a new loop renews its session's fill
set, so a fill gone since the last loop switches between loops and never
inside one, and what changed under the model since its last loop is told
as a step: the workspace was prepared over what that loop left."""

from collections.abc import Callable, Sequence
from datetime import datetime

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.agent_step import Actor, AgentStep, AgentStepType, Origin
from acme.om.agent_steps.types.content import Content, TextBlock
from acme.om.agent_steps.types.header import MarkHeader
from acme.om.agents.hooks import AttachedToolsets, LoopHooksInterface, LoopStart
from acme.om.base import new_id, utcnow
from acme.om.context import TenantContext
from acme.om.language_models.manager import LanguageModelsManagerInterface


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
    models manager every namespace reaches, read at call time, since the
    root builds it after the loop's hooks are set."""

    def __init__(
        self,
        inner: LoopHooksInterface,
        language_models: Callable[[], LanguageModelsManagerInterface],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._language_models = language_models
        self._clock = clock

    async def attached_toolsets(
        self, ctx: TenantContext, agent_session: AgentSession
    ) -> AttachedToolsets:
        return await self._inner.attached_toolsets(ctx, agent_session)

    async def before_first_call(self, ctx: TenantContext, start: LoopStart) -> Sequence[AgentStep]:
        if start.new_loop:
            # A fill gone since the last loop switches here, between loops,
            # and never inside one. Renewing twice leaves what once left.
            await self._language_models().renew_fill_set(
                ctx, start.agent_session.id, start.epoch, start.loop_id
            )
        steps = list(await self._inner.before_first_call(ctx, start))
        if start.workspace.changed is not None:
            steps.append(changed_step(start, start.workspace.changed, self._clock()))
        return steps
