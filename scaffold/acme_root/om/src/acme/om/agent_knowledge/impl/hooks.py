"""The loop's hooks that recall a session's agent knowledge as it starts:
before a session's first model call, the reviewed entries its subject
triggers arrive in it, as data, so the first call reads them and the
session does not rediscover its environment. No workspace is prepared by
then, and none is needed.

A session's subject is its title and what its principals said to it so
far. A session that has made a model request recalls nothing more here;
an entry recalled once is never recalled twice."""

from collections.abc import Callable, Sequence

from acme.infra.agent_workspaces import AgentWorkspace
from acme.om.agent_knowledge.manager import AgentKnowledgeManagerInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agents.hooks import AttachedToolsets, LoopHooksInterface, LoopStart
from acme.om.attribution.rules import principal_authored
from acme.om.context import TenantContext

FIRST_STEPS = 200
"""The steps a session's subject is read from: its start, before a call."""


class LoopHooksRecallImpl(LoopHooksInterface):
    """`agent_knowledge`, `sessions`, and `steps` answer at call time: a root
    builds these hooks before the managers they read. `inner` answers the
    rest."""

    def __init__(
        self,
        inner: LoopHooksInterface,
        agent_knowledge: Callable[[], AgentKnowledgeManagerInterface],
        sessions: Callable[[], AgentSessionsManagerInterface],
        steps: Callable[[], AgentStepsManagerInterface],
    ) -> None:
        self._inner = inner
        self._agent_knowledge = agent_knowledge
        self._sessions = sessions
        self._steps = steps

    async def attached_toolsets(
        self, ctx: TenantContext, agent_session: AgentSession
    ) -> AttachedToolsets:
        return await self._inner.attached_toolsets(ctx, agent_session)

    async def before_first_call(self, ctx: TenantContext, start: LoopStart) -> Sequence[AgentStep]:
        session = start.agent_session
        if session.speaker is None:
            # No model request yet: this loop starts the session.
            page = await self._steps().get_agent_steps(ctx, session.id, 0, FIRST_STEPS)
            said = [step.as_text() for step in page.items if principal_authored(step)]
            (opened,) = await self._sessions().open_titles(ctx, [session])
            await self._agent_knowledge().recall(
                ctx, session.id, "\n".join([opened.title.said(), *said])
            )
        return await self._inner.before_first_call(ctx, start)

    async def workspace_prepared(
        self, ctx: TenantContext, start: LoopStart, workspace: AgentWorkspace
    ) -> Sequence[AgentStep]:
        return await self._inner.workspace_prepared(ctx, start, workspace)
