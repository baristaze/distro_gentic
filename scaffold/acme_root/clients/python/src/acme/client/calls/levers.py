"""The levers namespace's calls: the operator plane's reading of what an
org's sessions reached and how often each stalled."""

from datetime import datetime
from uuid import UUID

from acme.client.transport import Transport
from acme.client.types.levers import LeverReadingView


class LeversCalls(Transport):
    """The operator plane's lever reading. The bearer is an operator token."""

    async def admin_levers(
        self, org_id: UUID, since: datetime, until: datetime
    ) -> LeverReadingView:
        """The agent playbooks and agent knowledge the org's sessions created in `[since,
        until)` reached, ranked by how much more often the sessions that
        reached them stalled; a read under `read`."""
        body = await self.request(
            "GET",
            f"/v1/admin/orgs/{org_id}/levers",
            params={"since": since.isoformat(), "until": until.isoformat()},
        )
        return LeverReadingView.model_validate(body)
