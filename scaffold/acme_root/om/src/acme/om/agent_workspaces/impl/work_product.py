"""What a session delivered, for the evidence: its branch as the bound
repository holds it, read outside the workspace, never from what the agent
says of it, with the checkout of the workspace this host holds telling
only what was not delivered. A session whose workspace this host does not
hold, or whose agent project binds no repository, has nothing read, and says
so, so no success counts on a guess."""

from uuid import UUID

from acme.om.agent_workspaces.impl.tools import HeldWorkspaces
from acme.om.agent_workspaces.manager import AgentWorkspacesManagerInterface
from acme.om.context import TenantContext
from acme.om.evidence.types.validation import WorkProduct
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import Unavailable


class WorkProductAgentWorkspacesImpl(WorkProductInterface):
    def __init__(
        self, agent_workspaces: AgentWorkspacesManagerInterface, held: HeldWorkspaces
    ) -> None:
        self._agent_workspaces = agent_workspaces
        self._held = held

    async def delivered(self, ctx: TenantContext, session_id: UUID) -> WorkProduct | None:
        workspace = self._held.get(session_id)
        if workspace is None:
            raise Unavailable(f"the workspace of session {session_id} is not held here")
        return await self._agent_workspaces.work_product(ctx, workspace)
