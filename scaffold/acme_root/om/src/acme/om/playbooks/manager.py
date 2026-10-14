"""The playbooks swimlane: a team's procedures as versioned, executable
briefs in the Agent Skills format, their gates in a namespaced metadata
extension. Only a person publishes a playbook. A principal in person, or
an agent automation a person saved, invokes one: its brief reaches the session
as that principal's message, and its gates join the session's policy,
where they only narrow it. A person pins one to a kind as its manual:
each new session of the kind holds its brief as its standing text and
its gates in its policy."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.playbooks.types.playbook import (
    Playbook,
    PlaybookDraft,
    PlaybookGate,
    PlaybookInvocation,
    PlaybookPin,
)


class PlaybooksManagerInterface(ABC):
    @abstractmethod
    async def publish(
        self, ctx: TenantContext, draft: PlaybookDraft, *, playbook_id: UUID | None = None
    ) -> Playbook:
        """The next version of the draft's name, announced, by a person in
        person: a context an agent's call runs under is `NotAuthorized`, so
        no agent writes the brief the next session follows. The version
        carries what the lever checks find in it, against the kinds it
        reaches; a finding advises and never refuses the publish. An id
        written already answers that version as stored, so a retry
        publishes none; one another tenant holds is `TenantMismatch`."""
        ...

    @abstractmethod
    async def get_playbook(self, ctx: TenantContext, name: str) -> Playbook:
        """The latest version of a name; none is `NotFound`."""
        ...

    @abstractmethod
    async def invoke(self, ctx: TenantContext, session_id: UUID, name: str) -> PlaybookInvocation:
        """Brings the latest version into a session, by a principal in
        person who may instruct it: its gates hold there from now on, and
        its brief arrives as the caller's message. An agent's call is
        `NotAuthorized`. Invoked again, the version's invocation answers."""
        ...

    @abstractmethod
    async def invoke_version(
        self, ctx: TenantContext, session_id: UUID, playbook_id: UUID
    ) -> PlaybookInvocation:
        """Brings one version into a session as an agent automation's firing runs,
        under the context it runs as, which may instruct the session: as
        `invoke` does, but never in person, since the person who saved the
        agent automation chose the playbook then, as they wrote its brief. Only an
        agent automation's action calls it, and no tool holds it. A version the
        tenant does not hold is `NotFound`."""
        ...

    @abstractmethod
    async def pin(
        self, ctx: TenantContext, kind: str, name: str, project_id: UUID | None = None
    ) -> PlaybookPin:
        """Pins the name's latest version to a kind as its manual, for the
        tenant's sessions of the kind, or those of one project, by a person
        in person who manages its members: an agent's call is
        `NotAuthorized`. Each session of the kind made from now on pins the
        version; one made before keeps its own. Pinned again, the slot
        names the version then latest. A kind the tenant's sessions cannot
        start on is `UnknownAgentKind`, a project the tenant does not hold
        or a name with no version `NotFound`, and a brief past what a
        session's standing text holds `ValidationFailed`, with nothing
        pinned."""
        ...

    @abstractmethod
    async def unpin(
        self, ctx: TenantContext, kind: str, project_id: UUID | None = None
    ) -> PlaybookPin:
        """Takes the kind's pin for the tenant, or for one project, away, by
        a person in person who manages its members, and answers it. A
        session made with it keeps it. None is `NotFound`."""
        ...

    @abstractmethod
    async def pins(self, ctx: TenantContext) -> tuple[PlaybookPin, ...]:
        """The tenant's pins, by kind, the tenant's before a project's."""
        ...

    @abstractmethod
    async def gates_of(self, ctx: TenantContext, session_id: UUID) -> tuple[PlaybookGate, ...]:
        """The gates of every playbook the session, or a session above it in
        its tree, invoked, a session marked deleted included: a sub-agent
        meets every gate its ancestors met. A session of the chain that
        cannot be read is `NotFound`, since the gates it invoked are unknown."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its versions and
        its invocations, a batch at most a call. Any other tenant returns 0."""
        ...
