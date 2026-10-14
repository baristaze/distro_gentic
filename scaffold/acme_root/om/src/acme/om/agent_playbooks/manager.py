"""The agent playbooks swimlane: a team's procedures as versioned, executable
briefs in the Agent Skills format, their gates in a namespaced metadata
extension. Only a person publishes an agent playbook. A principal in person, or
an agent automation a person saved, invokes one: its brief reaches the session
as that principal's message, and its gates join the session's policy,
where they only narrow it. A person pins one to a kind as its kind manual:
each new session of the kind holds its brief as its standing text and
its gates in its policy."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.agent_playbooks.types.agent_playbook import (
    AgentPlaybook,
    AgentPlaybookDraft,
    AgentPlaybookGate,
    AgentPlaybookInvocation,
    AgentPlaybookPin,
)
from acme.om.context import TenantContext


class AgentPlaybooksManagerInterface(ABC):
    @abstractmethod
    async def publish(
        self,
        ctx: TenantContext,
        draft: AgentPlaybookDraft,
        *,
        agent_playbook_id: UUID | None = None,
    ) -> AgentPlaybook:
        """The next version of the draft's name, announced, by a person in
        person: a context an agent's call runs under is `NotAuthorized`, so
        no agent writes the brief the next session follows. The version
        carries what the lever checks find in it, against the kinds it
        reaches; a finding advises and never refuses the publish. An id
        written already answers that version as stored, so a retry
        publishes none; one another tenant holds is `TenantMismatch`."""
        ...

    @abstractmethod
    async def get_agent_playbook(self, ctx: TenantContext, name: str) -> AgentPlaybook:
        """The latest version of a name; none is `NotFound`."""
        ...

    @abstractmethod
    async def invoke(
        self, ctx: TenantContext, session_id: UUID, name: str
    ) -> AgentPlaybookInvocation:
        """Brings the latest version into a session, by a principal in
        person who may instruct it: its gates hold there from now on, and
        its brief arrives as the caller's message. An agent's call is
        `NotAuthorized`. Invoked again, the version's invocation answers."""
        ...

    @abstractmethod
    async def invoke_version(
        self, ctx: TenantContext, session_id: UUID, agent_playbook_id: UUID
    ) -> AgentPlaybookInvocation:
        """Brings one version into a session as an agent automation's firing runs,
        under the context it runs as, which may instruct the session: as
        `invoke` does, but never in person, since the person who saved the
        agent automation chose the agent playbook then, as they wrote its brief. Only an
        agent automation's action calls it, and no tool holds it. A version the
        tenant does not hold is `NotFound`."""
        ...

    @abstractmethod
    async def pin(
        self, ctx: TenantContext, kind: str, name: str, agent_project_id: UUID | None = None
    ) -> AgentPlaybookPin:
        """Pins the name's latest version to a kind as its kind manual, for the
        tenant's sessions of the kind, or those of one agent project, by a person
        in person who manages its members: an agent's call is
        `NotAuthorized`. Each session of the kind made from now on pins the
        version; one made before keeps its own. Pinned again, the slot
        names the version then latest. A kind the tenant's sessions cannot
        start on is `UnknownAgentKind`, an agent project the tenant does not hold
        or a name with no version `NotFound`, and a brief past what a
        session's standing text holds `ValidationFailed`, with nothing
        pinned."""
        ...

    @abstractmethod
    async def unpin(
        self, ctx: TenantContext, kind: str, agent_project_id: UUID | None = None
    ) -> AgentPlaybookPin:
        """Takes the kind's pin for the tenant, or for one agent project, away, by
        a person in person who manages its members, and answers it. A
        session made with it keeps it. None is `NotFound`."""
        ...

    @abstractmethod
    async def pins(self, ctx: TenantContext) -> tuple[AgentPlaybookPin, ...]:
        """The tenant's pins, by kind, the tenant's before an agent project's."""
        ...

    @abstractmethod
    async def gates_of(self, ctx: TenantContext, session_id: UUID) -> tuple[AgentPlaybookGate, ...]:
        """The gates of every agent playbook the session, or a session above it in
        its tree, invoked, a session marked deleted included: a sub-agent
        meets every gate its ancestors met. A session of the chain that
        cannot be read is `NotFound`, since the gates it invoked are unknown."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its versions and
        its invocations, a batch at most a call. Any other tenant returns 0."""
        ...
