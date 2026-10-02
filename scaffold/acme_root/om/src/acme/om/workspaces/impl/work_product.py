"""What a session delivered, for the evidence: its branch as the bound
repository holds it, read outside the workspace, never from what the agent
says of it, with the checkout of the workspace this host holds telling
only what was not delivered. A session whose workspace this host does not
hold, or whose project binds no repository, has nothing read, and says
so, so no success counts on a guess."""

from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence.types.validation import Delivery
from acme.om.evidence.work_product import WorkProductInterface
from acme.om.exceptions import Unavailable
from acme.om.workspaces.impl.tools import HeldWorkspaces
from acme.om.workspaces.manager import WorkspacesManagerInterface


class WorkProductWorkspacesImpl(WorkProductInterface):
    def __init__(self, workspaces: WorkspacesManagerInterface, held: HeldWorkspaces) -> None:
        self._workspaces = workspaces
        self._held = held

    async def delivered(self, ctx: TenantContext, session_id: UUID) -> Delivery | None:
        workspace = self._held.get(session_id)
        if workspace is None:
            raise Unavailable(f"the workspace of session {session_id} is not held here")
        return await self._workspaces.delivery(ctx, workspace)
