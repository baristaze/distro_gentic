"""The playbooks swimlane: a team's procedures as versioned, executable
briefs in the Agent Skills format, their gates in a namespaced metadata
extension. Only a person publishes a playbook, and only a principal in
person invokes one. Its brief reaches the session as that principal's
message, and its gates join the session's policy, where they only narrow
it."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.playbooks.types.playbook import (
    Playbook,
    PlaybookDraft,
    PlaybookGate,
    PlaybookInvocation,
)


class PlaybooksManagerInterface(ABC):
    @abstractmethod
    async def publish(
        self, ctx: TenantContext, draft: PlaybookDraft, *, playbook_id: UUID | None = None
    ) -> Playbook:
        """The next version of the draft's name, announced, by a person in
        person: a context an agent's call runs under is `NotAuthorized`, so
        no agent writes the brief the next session follows. An id written
        already answers that version as stored, so a retry publishes none;
        one another tenant holds is `TenantMismatch`."""
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
