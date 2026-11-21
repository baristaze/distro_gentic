"""The engine's agents, each new session made with its kind's own manuals.

A decorator over the engine's agents manager, behind the same interface,
which the platform's root puts beneath every other layer of agents, so no
root can make a session without it. A start, a question that starts its
session, a spawn, and a hand-off put the manuals the session's kind ships
in its folder (`folders.KindFolder.manual`) first in the standing text the
session pins, before the kind manual its tenant pinned and any text its
maker sent: so they render whole in the system layer of every request,
as the kind's own, and no tenant reads, changes, or removes them where it
keeps its own. A repeat of a make sends the same text, which the engine
lands once. A kind that ships none is passed through as it is, and every
other operation is the engine's, unchanged."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.report import Report
from acme.om.agents.types.request import (
    MAX_STANDING,
    Handoff,
    Question,
    Spawn,
    Start,
    SwitchStanding,
)
from acme.om.agents.types.result import Result, Verdict
from acme.om.agents.types.tree import AgentTree
from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.tools.tool import TakeSnapshot


class AgentsManagerOwnManualsImpl(AgentsManagerInterface):
    """`manuals` holds each kind's own manuals, by its name, as a session
    receives them; a kind it does not name ships none."""

    def __init__(self, inner: AgentsManagerInterface, manuals: Mapping[str, str]) -> None:
        self._inner = inner
        self._manuals = manuals

    async def start_agent_session(self, ctx: TenantContext, start: Start) -> AgentSession:
        return await self._inner.start_agent_session(ctx, self._with(start))

    async def ask(self, ctx: TenantContext, question: Question) -> AgentStep:
        if question.start is None:
            return await self._inner.ask(ctx, question)
        made = question.model_copy(update={"start": self._with(question.start)})
        return await self._inner.ask(ctx, made)

    async def switch_standing(
        self, ctx: TenantContext, agent_session_id: UUID, switch: SwitchStanding
    ) -> AgentStep:
        return await self._inner.switch_standing(ctx, agent_session_id, switch)

    async def require_instructor(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        await self._inner.require_instructor(ctx, agent_session_id)

    async def spawn(
        self, ctx: TenantContext, parent_id: UUID, spawn: Spawn, fork: TakeSnapshot | None = None
    ) -> AgentSession:
        return await self._inner.spawn(ctx, parent_id, self._with(spawn), fork)

    async def tree_of(self, ctx: TenantContext, agent_session_id: UUID) -> AgentTree:
        return await self._inner.tree_of(ctx, agent_session_id)

    async def set_deadline(
        self, ctx: TenantContext, agent_session_id: UUID, deadline: datetime | None
    ) -> AgentTree:
        return await self._inner.set_deadline(ctx, agent_session_id, deadline)

    async def cancel_children(self, ctx: TenantContext, agent_session_id: UUID) -> tuple[UUID, ...]:
        return await self._inner.cancel_children(ctx, agent_session_id)

    async def report_to_parent(
        self, ctx: TenantContext, agent_session_id: UUID, report: Report
    ) -> AgentStep | None:
        return await self._inner.report_to_parent(ctx, agent_session_id, report)

    async def hand_off(
        self, ctx: TenantContext, agent_session_id: UUID, handoff: Handoff
    ) -> AgentSession:
        return await self._inner.hand_off(ctx, agent_session_id, self._with(handoff))

    async def judge_result(
        self, ctx: TenantContext, agent_session_id: UUID, result: Result
    ) -> Verdict:
        return await self._inner.judge_result(ctx, agent_session_id, result)

    async def purge_tree(self, org_id: UUID, tree_id: UUID) -> bool:
        return await self._inner.purge_tree(org_id, tree_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)

    def _with[R: Start | Spawn | Handoff](self, request: R) -> R:
        """The request with its kind's own manuals first in its standing
        text, before what the layers above and its maker put there; the
        whole is held to the standing text's bound, as the engine holds it,
        with the reason."""
        manual = self._manuals.get(request.kind, "")
        if not manual:
            return request
        text = f"{manual}\n\n{request.standing}" if request.standing else manual
        if len(text) > MAX_STANDING:
            raise ValidationFailed(
                f"the {request.kind} kind's own manuals and the standing text sent are"
                f" {len(text)} characters, past the bound of {MAX_STANDING} a session's"
                " standing text holds"
            )
        return request.model_copy(update={"standing": text})
