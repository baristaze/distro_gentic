"""The engine's agents, each new session made with its kind's manual.

A decorator over the engine's agents manager, behind the same interface.
A start, a spawn, and a hand-off of a session not yet made read the
playbook the tenant pinned to its kind, in its project or else for the
tenant, record that version as the session's pinned invocation, and send
its brief as the session's standing text: so its gates hold from the
session's first call, and its text renders whole in the system layer of
every request. A session that stands already is passed through as it is,
so one made before a pin, or a re-pin, keeps the manual it was made with.
Every other operation is the engine's, unchanged."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.om.agent_sessions.storage import AgentSessionStorageInterface
from acme.om.agent_sessions.types.agent_session import AgentSession
from acme.om.agents import AgentsManagerInterface
from acme.om.agents.types.kind import AgentKind
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
from acme.om.playbooks.rules import skill_md
from acme.om.playbooks.storage import PlaybookStorageInterface
from acme.om.playbooks.types.playbook import Playbook, PlaybookInvocation
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.steps.types.step import Step
from acme.om.tools.tool import TakeSnapshot


class AgentsManagerManualImpl(AgentsManagerInterface):
    def __init__(
        self,
        inner: AgentsManagerInterface,
        storage: PlaybookStorageInterface,
        session_rows: AgentSessionStorageInterface,
        projects: SessionProjectsInterface,
        per_session: int,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._inner = inner
        self._storage = storage
        self._session_rows = session_rows
        self._projects = projects
        self._per_session = per_session
        self._clock = clock

    async def start_session(self, ctx: TenantContext, start: Start) -> AgentSession:
        # A start in a project wrote the session's project row before it.
        manual = await self._manual(ctx, start.id, start.kind, start.id)
        return await self._inner.start_session(ctx, _with(start, manual))

    async def switch_standing(
        self, ctx: TenantContext, session_id: UUID, switch: SwitchStanding
    ) -> Step:
        return await self._inner.switch_standing(ctx, session_id, switch)

    async def require_instructor(self, ctx: TenantContext, session_id: UUID) -> None:
        await self._inner.require_instructor(ctx, session_id)

    async def spawn(
        self, ctx: TenantContext, parent_id: UUID, spawn: Spawn, fork: TakeSnapshot | None = None
    ) -> AgentSession:
        # A child stands in its parent's project.
        manual = await self._manual(ctx, spawn.id, spawn.kind, parent_id)
        return await self._inner.spawn(ctx, parent_id, _with(spawn, manual), fork)

    async def tree_of(self, ctx: TenantContext, session_id: UUID) -> AgentTree:
        return await self._inner.tree_of(ctx, session_id)

    async def kind_of(self, ctx: TenantContext, session_id: UUID) -> AgentKind:
        return await self._inner.kind_of(ctx, session_id)

    async def set_deadline(
        self, ctx: TenantContext, session_id: UUID, deadline: datetime | None
    ) -> AgentTree:
        return await self._inner.set_deadline(ctx, session_id, deadline)

    async def cancel_children(self, ctx: TenantContext, session_id: UUID) -> tuple[UUID, ...]:
        return await self._inner.cancel_children(ctx, session_id)

    async def report_to_parent(
        self, ctx: TenantContext, session_id: UUID, report: Report
    ) -> Step | None:
        return await self._inner.report_to_parent(ctx, session_id, report)

    async def hand_off(
        self, ctx: TenantContext, session_id: UUID, handoff: Handoff
    ) -> AgentSession:
        # A hand-over stands in the project of the session it came from.
        manual = await self._manual(ctx, handoff.id, handoff.kind, session_id)
        return await self._inner.hand_off(ctx, session_id, _with(handoff, manual))

    async def judge_result(self, ctx: TenantContext, session_id: UUID, result: Result) -> Verdict:
        return await self._inner.judge_result(ctx, session_id, result)

    async def purge_tree(self, org_id: UUID, tree_id: UUID) -> bool:
        return await self._inner.purge_tree(org_id, tree_id)

    async def purge_tenant(self, ctx: TenantContext) -> int:
        return await self._inner.purge_tenant(ctx)

    async def _manual(self, ctx: TenantContext, session_id: UUID, kind: str, origin: UUID) -> str:
        """The brief a new session pins as its standing text, its version
        recorded first as the session's pinned invocation, so its gates
        hold before the session can make a call; empty when the session
        stands already or its kind has no pin. A retry of a make that
        recorded one pins that version, whatever the pin names now.
        `origin` is the session whose project the new one stands in."""
        ctx.require(Permission.WRITE)
        if await self._session_rows.read_session(ctx.org_id, session_id) is not None:
            return ""
        recorded = [
            invocation
            for invocation in await self._storage.read_invocations(
                ctx.org_id, session_id, self._per_session
            )
            if invocation.pinned
        ]
        if recorded:
            playbook = await self._storage.read_playbook(ctx.org_id, recorded[0].playbook_id)
            return "" if playbook is None else skill_md(playbook)
        playbook = await self._pinned(ctx, kind, origin)
        if playbook is None:
            return ""
        await self._storage.create_invocation(
            ctx.org_id,
            PlaybookInvocation(
                id=new_id(),
                created_at=self._clock(),
                session_id=session_id,
                playbook_id=playbook.id,
                name=playbook.name,
                version=playbook.version,
                invoked_by=ctx.user_id,
                pinned=True,
            ),
        )
        return skill_md(playbook)

    async def _pinned(self, ctx: TenantContext, kind: str, origin: UUID) -> Playbook | None:
        """The version pinned to the kind in the origin's project, or else
        the tenant's."""
        project_id = await self._projects.project_of(ctx, origin)
        pin = None
        if project_id is not None:
            pin = await self._storage.read_pin(ctx.org_id, kind, project_id)
        if pin is None:
            pin = await self._storage.read_pin(ctx.org_id, kind, None)
        if pin is None:
            return None
        return await self._storage.read_playbook(ctx.org_id, pin.playbook_id)


def _with[R: Start | Spawn | Handoff](request: R, manual: str) -> R:
    """The request with the manual first in its standing text, before any
    its maker sent; the two together are held to the standing text's
    bound, as the engine holds it, with the reason."""
    if not manual:
        return request
    text = f"{manual}\n\n{request.standing}" if request.standing else manual
    if len(text) > MAX_STANDING:
        raise ValidationFailed(
            f"the kind's manual and the standing text sent are {len(text)} characters,"
            f" past the bound of {MAX_STANDING} a session's standing text holds"
        )
    return request.model_copy(update={"standing": text})
