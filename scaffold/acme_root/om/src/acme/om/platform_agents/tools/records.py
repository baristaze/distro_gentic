"""The `records` toolset: the assistant's readers of the tenant's live
records, its sessions and what they wait on, its agent projects, and its
agent automations, each through the asking person's own permissions. The
draft of the tenant's tool policy, which reads the live policy and writes
nothing, sits here too."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.types.agent_automation import AgentAutomation
from acme.om.agent_automations.types.agent_automation import Limits as AgentAutomationLimits
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_projects.types.agent_project import AgentProject
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.kinds import AgentSessionWorkKind
from acme.om.agent_sessions.types.agent_session import AgentSession, AgentSessionStatus
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.types.agent_step import AgentStep
from acme.om.agent_steps.types.header import ParkReason, ToolRequestHeader
from acme.om.agents.loop_rules import APPROVAL_UNLOCK
from acme.om.base import OmBase
from acme.om.context import Role, TenantContext
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.types.host import HostStatus
from acme.om.park_alerts.rules import held_calls
from acme.om.platform_agents import kinds, rules
from acme.om.platform_agents.tools.base import HOSTS_MAX, LIST_MAX, NativeToolImpl, PageInput
from acme.om.platform_agents.types.draft import PolicyDraft
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.rules import approver_roles
from acme.om.tools.tool import ToolRuntime
from acme.om.tools.types.policy import ApproverRule, ToolPolicyRule
from acme.om.tools.types.tool import Effect, ToolClass, ToolInput, ToolMode, ToolSpec
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkStatus

# The assistant's readers. Each reads through the asking person's own
# permissions: the call's context is theirs, so a row of another tenant's,
# or one marked deleted, is not found, as one that never existed is not. Each
# answers a record's shape, never a session's content, and bounds its list.

SESSION_SCAN = 100
"""The root sessions one list_sessions call reads at most, newest first,
each with the sub-agents under it, before it filters by status, park reason,
and agent project: the call stays one read of a page, a read of each tree's
children, and at most a lookup of an agent project for each session it reads, and
its answer says where to read on."""
RUNS_MAX = 20  # an agent automation's recent runs one read answers at most
CHILDREN_MAX = 20  # the sub-agents read_session answers at most
CHILDREN_PAGE = 100  # the sub-agents of one parent a tree's read takes at a time
HISTORY_PAGE = 200  # steps one read of a history takes


class SessionInput(ToolInput):
    agent_session_id: UUID


class HeldCall(OmBase):
    """A call the session holds for a person's decision: the tool, its
    class, and the roles the tenant's policy lets decide that class."""

    seq: int
    tool: str
    authorization_class: str
    requested_at: datetime
    decided_by: tuple[Role, ...]


class ChildLine(OmBase):
    agent_session_id: UUID
    kind: str
    status: AgentSessionStatus


class AuthSessionState(OmBase):
    """Where a session stands, as its record says: never its content."""

    kind: str
    kind_version: int
    title: str
    started_by: UUID
    agent_project_id: UUID | None = None
    parent_id: UUID | None = None
    handed_off_from: UUID | None = None
    status: AgentSessionStatus
    waiting_input: bool  # a message that woke it has not reached the model yet
    park_reason: ParkReason | None = None
    unlock: str | None = None  # what clears the park: an approval, a budget's id, a job
    retry_at: datetime | None = None
    held_calls: tuple[HeldCall, ...] = ()  # when it waits on an approval
    children: tuple[ChildLine, ...] = ()  # when it waits on its sub-agents
    archived: bool


async def tree_of(
    sessions: AgentSessionsManagerInterface, ctx: TenantContext, root: AgentSession
) -> list[AgentSession]:
    """A root and every sub-agent under it, each parent before its children,
    read through the engine's children of each parent, which answers only
    for a parent the person sees."""
    tree = [root]
    index = 0
    while index < len(tree):
        parent = tree[index]
        index += 1
        after: UUID | None = None
        while True:
            page = await sessions.get_children(ctx, parent.id, after, CHILDREN_PAGE)
            tree.extend(page.items)
            if not page.has_more or not page.items:
                break
            after = page.items[-1].id
    return tree


async def history_of(
    steps: AgentStepsManagerInterface, ctx: TenantContext, agent_session_id: UUID
) -> list[AgentStep]:
    """A session's whole history, in order, a page at a time. Read after the
    session itself, so another tenant's is never reached."""
    history: list[AgentStep] = []
    while True:
        after = history[-1].seq if history else 0
        page = await steps.get_agent_steps(ctx, agent_session_id, after, HISTORY_PAGE)
        history.extend(page.items)
        if not page.has_more or not page.items:
            return history


class ReadSessionImpl(NativeToolImpl):
    """Reads one session of the tenant: its record, and what its park waits
    on. A park on an approval answers each call it holds and who may decide
    it; a park on its sub-agents answers them."""

    SPEC = ToolSpec(
        name=kinds.READ_SESSION,
        description=(
            "Reads where a session of the tenant stands: its kind, title, agent project, who "
            "started it, whether it is pending, running, parked, or idle, why it is parked "
            "and what clears it, and when it tries again. A session parked on an approval "
            "answers each call it holds and the roles that may decide it; one parked on its "
            "sub-agents answers them."
        ),
        input_model=SessionInput,
        output_model=AuthSessionState,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        steps: Callable[[], AgentStepsManagerInterface],
        policies: Callable[[], ToolsManagerInterface],
        agent_projects: Callable[[], AgentProjectsManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._steps = steps
        self._policies = policies
        self._agent_projects = agent_projects

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, SessionInput)
        session = await self._sessions().get_agent_session(ctx, call_input.agent_session_id)
        park = session.park
        agent_project = await self._agent_projects().agent_project_of(ctx, session.id)
        held: tuple[HeldCall, ...] = ()
        if park is not None and park.reason is ParkReason.PERSON and park.unlock == APPROVAL_UNLOCK:
            policy = await self._policies().get_policy(ctx)
            held = tuple(
                held_call(request, approver_roles(policy, request.header.authorization_class))
                for request in held_calls(await history_of(self._steps(), ctx, session.id))
                if isinstance(request.header, ToolRequestHeader)
            )
        children: tuple[ChildLine, ...] = ()
        if park is not None and park.reason is ParkReason.CHILDREN:
            page = await self._sessions().get_children(ctx, session.id, None, CHILDREN_MAX)
            children = tuple(
                ChildLine(agent_session_id=child.id, kind=child.kind, status=child.status)
                for child in page.items
            )
        return AuthSessionState(
            kind=session.kind,
            kind_version=session.kind_version,
            title=session.title,
            started_by=session.created_by,
            agent_project_id=None if agent_project is None else agent_project.id,
            parent_id=session.parent_id,
            handed_off_from=session.handed_off_from,
            status=session.status,
            waiting_input=session.pending_input is not None,
            park_reason=None if park is None else park.reason,
            unlock=None if park is None else park.unlock,
            retry_at=None if park is None else park.retry_at,
            held_calls=held,
            children=children,
            archived=session.archived_at is not None,
        )


def held_call(request: AgentStep, roles: tuple[Role, ...]) -> HeldCall:
    header = request.header
    assert isinstance(header, ToolRequestHeader)
    return HeldCall(
        seq=request.seq,
        tool=header.tool,
        authorization_class=header.authorization_class,
        requested_at=request.created_at,
        decided_by=roles,
    )


class SessionsQuery(ToolInput):
    status: AgentSessionStatus | None = None
    park_reason: ParkReason | None = None
    agent_project_id: UUID | None = None
    before: UUID | None = None  # the `next` an earlier answer gave
    limit: int = Field(default=20, ge=1, le=LIST_MAX)

    @model_validator(mode="after")
    def _a_park_reason_lists_parked_sessions(self) -> Self:
        if self.park_reason is not None and self.status not in (None, AgentSessionStatus.PARKED):
            raise ValueError("a park reason lists parked sessions: leave status out")
        return self


class SessionLine(OmBase):
    agent_session_id: UUID
    title: str
    kind: str
    status: AgentSessionStatus
    park_reason: ParkReason | None = None
    started_by: UUID
    created_at: datetime


class SessionList(OmBase):
    sessions: tuple[SessionLine, ...]
    next: UUID | None  # pass it as `before` to read on; none once the list is read


class ListSessionsImpl(NativeToolImpl):
    """Lists the tenant's sessions, newest first, by status, park reason, and
    agent project: each root the person sees, then the sub-agents under it, read
    through the engine's children of each parent, so a sub-agent of a root
    the person does not see is never listed. One call reads at most a scan's
    worth of roots, so a filter that matches few may answer fewer than its
    limit with a `next`. A tree is listed whole: the answer stops before a
    tree that would pass the limit, unless that tree comes first."""

    SPEC = ToolSpec(
        name=kinds.LIST_SESSIONS,
        description=(
            "Lists the tenant's sessions, newest first: each one's id, title, kind, "
            "status, park reason, who started it, and when. Filter by status, by park reason "
            "(parked sessions only), or by agent project. When the answer carries next, pass it as "
            "before to read on: a filter that matches few may answer fewer than limit."
        ),
        input_model=SessionsQuery,
        output_model=SessionList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        agent_projects: Callable[[], AgentProjectsManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._agent_projects = agent_projects

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, SessionsQuery)
        # A sub-agent waits under a root in any status, an idle one included,
        # so the scan reads every root, and the filter reads each session.
        page = await self._sessions().get_agent_sessions(ctx, None, call_input.before, SESSION_SCAN)
        found: list[SessionLine] = []
        listed: UUID | None = None  # the last root whose tree the answer holds
        for root in page.items:
            lines = [
                line
                for session in await tree_of(self._sessions(), ctx, root)
                if (line := await self._line(ctx, session, call_input)) is not None
            ]
            if found and len(found) + len(lines) > call_input.limit:
                return SessionList(sessions=tuple(found), next=listed)
            found.extend(lines)
            listed = root.id
            if len(found) >= call_input.limit:
                more = root.id != page.items[-1].id or page.has_more
                return SessionList(sessions=tuple(found), next=root.id if more else None)
        last = page.items[-1].id if page.items and page.has_more else None
        return SessionList(sessions=tuple(found), next=last)

    async def _line(
        self, ctx: TenantContext, session: AgentSession, query: SessionsQuery
    ) -> SessionLine | None:
        """The session's line when it passes the query's filters. A sub-agent
        marked deleted is read through to its own, and listed on no line."""
        if session.deleted_at is not None:
            return None
        reason = query.park_reason
        status = AgentSessionStatus.PARKED if reason is not None else query.status
        if status is not None and session.status is not status:
            return None
        if reason is not None and (session.park is None or session.park.reason is not reason):
            return None
        if query.agent_project_id is not None:
            agent_project = await self._agent_projects().agent_project_of(ctx, session.id)
            if agent_project is None or agent_project.id != query.agent_project_id:
                return None
        return SessionLine(
            agent_session_id=session.id,
            title=session.title,
            kind=session.kind,
            status=session.status,
            park_reason=None if session.park is None else session.park.reason,
            started_by=session.created_by,
            created_at=session.created_at,
        )


class WaitingItem(OmBase):
    """The session's loop on the work queue: the item made last for it."""

    status: WorkStatus
    lane: str
    queued_at: datetime
    available_at: datetime
    attempts: int
    max_attempts: int
    lease_expires_at: datetime | None = None
    running_ahead: int | None = None  # the tenant's loops running ahead of it, while queued


class PoolHost(OmBase):
    host_id: UUID
    name: str
    online: bool
    last_seen_at: datetime


class SessionWait(OmBase):
    """What a session waits on outside its own history: its loop's place on
    the work queue, and where it runs, with the hosts that may take it."""

    agent_session_id: UUID
    status: AgentSessionStatus
    park_reason: ParkReason | None = None
    retry_at: datetime | None = None
    loop: WaitingItem | None = None
    runs_in: str  # "cloud", or the pool it is pinned to
    pool_id: UUID | None = None
    hosts_online: int = 0
    hosts: tuple[PoolHost, ...] = ()  # the pool's, the one seen last first
    workspace_host: PoolHost | None = None  # the host that holds its workspace
    waits_for_a_host: bool  # no host of its pool online, or its workspace's host offline


CLOUD = "cloud"


class ReadWaitImpl(NativeToolImpl):
    """Reads what a session waits on beyond its park: its loop's item on the
    work queue, the tenant's own loops running ahead of it, and where it runs,
    the cloud or a pool of the tenant's hosts and which of them are online,
    and the host that holds its workspace, which it waits for while that
    host is offline."""

    SPEC = ToolSpec(
        name=kinds.READ_WAIT,
        description=(
            "Reads what a pending or slow session waits on: its loop's item on the work "
            "queue (queued or running, its lane, since when, its attempts, and how many of "
            "the tenant's loops run ahead of it), and where it runs: the cloud, or the "
            "tenant's pool it is pinned to, with the pool's hosts and which are online. A "
            "pinned session with no host online waits for one. A workspace lives on the host "
            "that prepared it: while that host is offline, the session waits for it, even "
            "with other hosts online, and its last_seen_at says since when."
        ),
        input_model=SessionInput,
        output_model=SessionWait,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(
        self,
        sessions: Callable[[], AgentSessionsManagerInterface],
        work: Callable[[], WorkManagerInterface],
        hosts: Callable[[], HostsManagerInterface],
        exec_relay: Callable[[], ExecRelayManagerInterface],
    ) -> None:
        self._sessions = sessions
        self._work = work
        self._hosts = hosts
        self._exec_relay = exec_relay

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, SessionInput)
        session = await self._sessions().get_agent_session(ctx, call_input.agent_session_id)
        item = await self._work().latest_for_target(ctx, AgentSessionWorkKind.LOOP, session.id)
        loop: WaitingItem | None = None
        if item is not None:
            queued = item.status is WorkStatus.QUEUED
            loop = WaitingItem(
                status=item.status,
                lane=item.lane,
                queued_at=item.created_at,
                available_at=item.available_at,
                attempts=item.attempts,
                max_attempts=item.max_attempts,
                lease_expires_at=item.lease_expires_at,
                running_ahead=await self._work().claimed_ahead(ctx, item) if queued else None,
            )
        placement = await self._hosts().placement_of(ctx, session.id)
        pool = placement.pool
        hosts: tuple[PoolHost, ...] = ()
        holder: HostStatus | None = None
        if pool is not None:
            hosts = tuple(
                _pool_host(status)
                for status in (await self._hosts().get_hosts(ctx, pool.id))[:HOSTS_MAX]
            )
            binding = await self._exec_relay().binding_of(ctx, session.id)
            if binding is not None:
                holder = await self._hosts().get_host(ctx, pool.id, binding.host_id)
                # A revoked host took the workspace with it: another host of
                # the pool prepares one, so nothing pins the session to it.
                if holder is not None and holder.host.revoked_at is not None:
                    holder = None
        park = session.park
        return SessionWait(
            agent_session_id=session.id,
            status=session.status,
            park_reason=None if park is None else park.reason,
            retry_at=None if park is None else park.retry_at,
            loop=loop,
            runs_in=CLOUD if pool is None else pool.name,
            pool_id=None if pool is None else pool.id,
            hosts_online=placement.hosts_online,
            hosts=hosts,
            workspace_host=None if holder is None else _pool_host(holder),
            waits_for_a_host=placement.waiting or (holder is not None and not holder.online),
        )


def _pool_host(status: HostStatus) -> PoolHost:
    return PoolHost(
        host_id=status.host.id,
        name=status.host.name,
        online=status.online,
        last_seen_at=status.host.last_seen_at,
    )


class AgentProjectInput(ToolInput):
    agent_project_id: UUID


class AgentProjectRead(OmBase):
    agent_project_id: UUID
    name: str
    repository: str  # its host and path, such as github.com/octo/reports
    created_at: datetime
    created_by: UUID


class AgentProjectList(OmBase):
    agent_projects: tuple[AgentProjectRead, ...]
    next: UUID | None  # pass it as `after` to read on; none once the list is read


def agent_project_read(agent_project: AgentProject) -> AgentProjectRead:
    return AgentProjectRead(
        agent_project_id=agent_project.id,
        name=agent_project.name,
        repository=f"{agent_project.repository.host}/{agent_project.repository.path}",
        created_at=agent_project.created_at,
        created_by=agent_project.created_by,
    )


class ListAgentProjectsImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_AGENT_PROJECTS,
        description=(
            "Lists the tenant's agent projects: each one's id, name, and the repository its work "
            "lands on. When the answer carries next, pass it as after to read on."
        ),
        input_model=PageInput,
        output_model=AgentProjectList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agent_projects: Callable[[], AgentProjectsManagerInterface]) -> None:
        self._agent_projects = agent_projects

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, PageInput)
        limit = call_input.limit
        rows = await self._agent_projects().list_agent_projects(ctx, call_input.after, limit + 1)
        shown = rows[:limit]
        more = len(rows) > limit
        return AgentProjectList(
            agent_projects=tuple(agent_project_read(p) for p in shown),
            next=shown[-1].id if more else None,
        )


class ReadAgentProjectImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.READ_AGENT_PROJECT,
        description=(
            "Reads one agent project of the tenant: its name, the repository its work lands on, "
            "and who made it when. Its sessions are list_sessions with its agent_project_id."
        ),
        input_model=AgentProjectInput,
        output_model=AgentProjectRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agent_projects: Callable[[], AgentProjectsManagerInterface]) -> None:
        self._agent_projects = agent_projects

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, AgentProjectInput)
        return agent_project_read(
            await self._agent_projects().get_agent_project(ctx, call_input.agent_project_id)
        )


class AgentAutomationLine(OmBase):
    agent_automation_id: UUID
    name: str
    trigger: str  # an event or a schedule
    action: str
    enabled: bool
    runs_as: str


class AgentAutomationList(OmBase):
    agent_automations: tuple[AgentAutomationLine, ...]
    next: UUID | None  # pass it as `after` to read on; none once the list is read


class AgentAutomationInput(ToolInput):
    agent_automation_id: UUID
    runs: int = Field(default=5, ge=1, le=RUNS_MAX)


class RunLine(OmBase):
    """One firing of an agent automation, as recorded: started, queued, or refused
    and why, the session it started or messaged, and how it ended."""

    run_id: UUID
    fired_at: datetime
    status: str
    refusal: str | None = None
    hop: int
    agent_session_id: UUID | None = None
    opened: bool
    outcome: str | None = None
    started_at: datetime | None = None
    closed_at: datetime | None = None


class AgentAutomationRead(OmBase):
    """An agent automation's shape and its recent runs: never the text a person
    briefed it with or an event brought."""

    agent_automation_id: UUID
    name: str
    enabled: bool
    runs_as: str
    own_events: bool
    trigger: str
    integrations: tuple[str, ...]
    arrivals: tuple[str, ...]
    effects: tuple[str, ...]
    every: timedelta | None = None
    action: str
    agent_kind: str | None = None
    agent_project_id: UUID | None = None
    agent_session_id: UUID | None = None
    limits: AgentAutomationLimits
    runs: tuple[RunLine, ...]  # newest first


def agent_automation_line(agent_automation: AgentAutomation) -> AgentAutomationLine:
    return AgentAutomationLine(
        agent_automation_id=agent_automation.id,
        name=agent_automation.name,
        trigger=agent_automation.trigger.kind,
        action=agent_automation.action.kind,
        enabled=agent_automation.enabled,
        runs_as=agent_automation.runs_as,
    )


class ListAgentAutomationsImpl(NativeToolImpl):
    SPEC = ToolSpec(
        name=kinds.LIST_AGENT_AUTOMATIONS,
        description=(
            "Lists the tenant's agent automations: each one's id, name, whether an event or a "
            "schedule fires it, what it does, whether it is on, and whom it runs as. When "
            "the answer carries next, pass it as after to read on."
        ),
        input_model=PageInput,
        output_model=AgentAutomationList,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agent_automations: Callable[[], AgentAutomationsManagerInterface]) -> None:
        self._agent_automations = agent_automations

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, PageInput)
        limit = call_input.limit
        rows = await self._agent_automations().list_agent_automations(
            ctx, call_input.after, limit + 1
        )
        shown = rows[:limit]
        return AgentAutomationList(
            agent_automations=tuple(agent_automation_line(a) for a in shown),
            next=shown[-1].id if len(rows) > limit else None,
        )


class ReadAgentAutomationImpl(NativeToolImpl):
    """Reads one agent automation of the tenant and its recent runs. The agent automation
    is read first, so another tenant's is not found before any run is."""

    SPEC = ToolSpec(
        name=kinds.READ_AGENT_AUTOMATION,
        description=(
            "Reads one agent automation of the tenant: what fires it, what it does, its limits "
            "(cost cap, rate, concurrency, queue, hop limit), whom it runs as, and its "
            "recent runs, newest first: each started, queued, or refused and why, the "
            "session it started or messaged, and how it ended."
        ),
        input_model=AgentAutomationInput,
        output_model=AgentAutomationRead,
        timeout=timedelta(seconds=10),
        authorization_class=ToolClass.READ,
        effect=Effect.READ_ONLY,
        interruptible=True,
        mode=ToolMode.SYNC,
    )

    def __init__(self, agent_automations: Callable[[], AgentAutomationsManagerInterface]) -> None:
        self._agent_automations = agent_automations

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, AgentAutomationInput)
        agent_automation = await self._agent_automations().get_agent_automation(
            ctx, call_input.agent_automation_id
        )
        runs = await self._agent_automations().get_runs(ctx, agent_automation.id, call_input.runs)
        trigger, action = agent_automation.trigger, agent_automation.action
        return AgentAutomationRead(
            agent_automation_id=agent_automation.id,
            name=agent_automation.name,
            enabled=agent_automation.enabled,
            runs_as=agent_automation.runs_as,
            own_events=agent_automation.own_events,
            trigger=trigger.kind,
            integrations=trigger.integrations,
            arrivals=trigger.arrivals,
            effects=trigger.effects,
            every=trigger.every,
            action=action.kind,
            agent_kind=action.agent_kind,
            agent_project_id=action.agent_project_id,
            agent_session_id=action.agent_session_id,
            limits=agent_automation.limits,
            runs=tuple(
                RunLine(
                    run_id=run.id,
                    fired_at=run.created_at,
                    status=run.status,
                    refusal=run.refusal,
                    hop=run.hop,
                    agent_session_id=run.agent_session_id,
                    opened=run.opened,
                    outcome=run.outcome,
                    started_at=run.started_at,
                    closed_at=run.closed_at,
                )
                for run in runs[: call_input.runs]
            ),
        )


class DraftInput(ToolInput):
    rules: tuple[ToolPolicyRule, ...] = ()
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

    async def run(self, ctx: TenantContext, call_input: ToolInput, runtime: ToolRuntime) -> OmBase:
        assert isinstance(call_input, DraftInput)
        live = await self._policies().get_policy(ctx)
        return rules.draft_policy(
            live, call_input.rules, call_input.approvers, self._tools, self._classes
        )
