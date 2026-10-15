"""The engine's agents, each new session made with its kind manual.

A decorator over the engine's agents manager, behind the same interface.
A start, a spawn, and a hand-off of a session not yet made read the
agent playbook the tenant pinned to its kind, in its agent project or else for the
tenant, record that version as the session's pinned invocation, and send
its brief as the session's standing text: so its gates hold from the
session's first call, and its text renders whole in the system layer of
every request. A repeat of a make sends the version the session
recorded, which the engine lands once, so a make cut off after the
session's row still pins its text; a session that stands with none
recorded is passed through as it is. So one made before a pin, or a
re-pin, keeps the kind manual it was made with. Every other operation is the
engine's, unchanged."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_playbooks.impl.manager import AgentPlaybooksOptions
from acme.om.agent_playbooks.rules import skill_md
from acme.om.agent_playbooks.storage import AgentPlaybookStorageInterface
from acme.om.agent_playbooks.types.agent_playbook import AgentPlaybook, AgentPlaybookInvocation
from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.report import Report
from acme.om.agents.types.request import (
    MAX_STANDING,
    Handoff,
    Spawn,
    Start,
    SwitchStanding,
)
from acme.om.agents.types.result import Result, Verdict
from acme.om.agents.types.tree import AgentTree
from acme.om.base import new_id, utcnow
from acme.om.context import Permission, TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.tools.tool import TakeSnapshot


class AgentsManagerKindManualImpl(AgentsManagerInterface):
    def __init__(
        self,
        inner: AgentsManagerInterface,
        storage: AgentPlaybookStorageInterface,
        session_rows: AgentSessionStorageInterface,
        agent_projects: SessionAgentProjectsInterface,
        options: AgentPlaybooksOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._storage = storage
        self._session_rows = session_rows
        self._agent_projects = agent_projects
        self._options = options
        self._clock = clock

    async def start_agent_session(self, ctx: TenantContext, start: Start) -> AgentSession:
        # A start in an agent project wrote the session's agent project row before it.
        kind_manual = await self._kind_manual(ctx, start.id, start.kind, start.id)
        return await self._inner.start_agent_session(ctx, _with(start, kind_manual))

    async def switch_standing(
        self, ctx: TenantContext, agent_session_id: UUID, switch: SwitchStanding
    ) -> AgentStep:
        return await self._inner.switch_standing(ctx, agent_session_id, switch)

    async def require_instructor(self, ctx: TenantContext, agent_session_id: UUID) -> None:
        await self._inner.require_instructor(ctx, agent_session_id)

    async def spawn(
        self, ctx: TenantContext, parent_id: UUID, spawn: Spawn, fork: TakeSnapshot | None = None
    ) -> AgentSession:
        # A child stands in its parent's agent project.
        kind_manual = await self._kind_manual(ctx, spawn.id, spawn.kind, parent_id)
        return await self._inner.spawn(ctx, parent_id, _with(spawn, kind_manual), fork)

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
        # A hand-over stands in the agent project of the session it came from.
        kind_manual = await self._kind_manual(ctx, handoff.id, handoff.kind, agent_session_id)
        return await self._inner.hand_off(ctx, agent_session_id, _with(handoff, kind_manual))

    async def judge_result(
        self, ctx: TenantContext, agent_session_id: UUID, result: Result
    ) -> Verdict:
        return await self._inner.judge_result(ctx, agent_session_id, result)

    async def purge_tree(self, org_id: UUID, tree_id: UUID) -> bool:
        return await self._inner.purge_tree(org_id, tree_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)

    async def _kind_manual(
        self, ctx: TenantContext, agent_session_id: UUID, kind: str, origin: UUID
    ) -> str:
        """The brief a new session pins as its standing text, its version
        recorded first as the session's pinned invocation, so its gates
        hold before the session can make a call. A repeat of a make that
        recorded one sends that version, whatever the pin names now, also
        when the session's row stands: the first may have stopped before
        its standing text, and the engine's standing step lands once.
        Empty when the session stands with none recorded, or its kind has
        no pin. `origin` is the session whose agent project the new one stands
        in."""
        ctx.require(Permission.WRITE)
        recorded = [
            invocation
            for invocation in await self._storage.read_invocations(
                ctx.org_id, agent_session_id, self._options.per_session
            )
            if invocation.pinned
        ]
        if recorded:
            agent_playbook = await self._storage.read_agent_playbook(
                ctx.org_id, recorded[0].agent_playbook_id
            )
            return "" if agent_playbook is None else skill_md(agent_playbook)
        if await self._session_rows.read_agent_session(ctx.org_id, agent_session_id) is not None:
            return ""
        agent_playbook = await self._pinned(ctx, kind, origin)
        if agent_playbook is None:
            return ""
        await self._storage.create_invocation(
            ctx.org_id,
            AgentPlaybookInvocation(
                id=new_id(),
                created_at=self._clock(),
                agent_session_id=agent_session_id,
                agent_playbook_id=agent_playbook.id,
                name=agent_playbook.name,
                version=agent_playbook.version,
                invoked_by=ctx.user_id,
                pinned=True,
            ),
        )
        return skill_md(agent_playbook)

    async def _pinned(self, ctx: TenantContext, kind: str, origin: UUID) -> AgentPlaybook | None:
        """The version pinned to the kind in the origin's agent project, or else
        the tenant's."""
        agent_project_id = await self._agent_projects.agent_project_of(ctx, origin)
        pin = None
        if agent_project_id is not None:
            pin = await self._storage.read_pin(ctx.org_id, kind, agent_project_id)
        if pin is None:
            pin = await self._storage.read_pin(ctx.org_id, kind, None)
        if pin is None:
            return None
        return await self._storage.read_agent_playbook(ctx.org_id, pin.agent_playbook_id)


def _with[R: Start | Spawn | Handoff](request: R, kind_manual: str) -> R:
    """The request with the kind manual first in its standing text, before any
    its maker sent; the two together are held to the standing text's
    bound, as the engine holds it, with the reason."""
    if not kind_manual:
        return request
    text = f"{kind_manual}\n\n{request.standing}" if request.standing else kind_manual
    if len(text) > MAX_STANDING:
        raise ValidationFailed(
            f"the kind manual and the standing text sent are {len(text)} characters,"
            f" past the bound of {MAX_STANDING} a session's standing text holds"
        )
    return request.model_copy(update={"standing": text})
