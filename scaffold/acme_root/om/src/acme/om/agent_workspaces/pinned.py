"""Whether a session's pinned workspace can ever be held where the session
runs, asked before its loop's first model call. The engine's loop checks the
spec its kind declares, which names no session; a session's pin may ask more
than its kind (an allowlist's egress, its agent project's workspace base),
so the platform's loop hooks ask this of the pin itself
(`acme.om.platform_loop_hooks`). The tools manager the platform runs answers
it, where it decides where each workspace is made
(`acme.om.agent_workspaces.impl.tools`)."""

from abc import ABC, abstractmethod
from uuid import UUID

from acme.infra.agent_workspaces import IsolationSpec
from acme.om.context import TenantContext


class PinnedWorkspacesInterface(ABC):
    @abstractmethod
    async def check_pinned(
        self, ctx: TenantContext, agent_session_id: UUID, asked: IsolationSpec
    ) -> None:
        """The session's pin, held to what the place its workspace is made
        can ever give, with nothing made: `IsolationRefused`, with its
        cause, for what a prepare there would refuse for good. A refusal
        that clears, and a session placed in a pool of its tenant's hosts,
        whose host answers, wait for the first call that reaches the
        workspace. A session never pinned is held to `asked`, its loop's
        spec."""
        ...
