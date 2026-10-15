"""The tools namespace's calls: a tenant's layer of tool policy, read, and
written under the version it was read at."""

from acme.client.transport import Transport
from acme.client.types.tools import (
    ToolPolicyRequest,
    ToolPolicyView,
)


class ToolsCalls(Transport):
    """The tenant's layer of tool policy."""

    async def tool_policy(self) -> ToolPolicyView:
        return ToolPolicyView.model_validate(await self.request("GET", "/v1/tools/policy"))

    async def write_tool_policy(self, layer: ToolPolicyRequest, *, version: int) -> ToolPolicyView:
        """The tenant's layer whole, on the version read; `precondition_failed`
        when it moved."""
        written = await self.request(
            "PUT",
            "/v1/tools/policy",
            json=layer.model_dump(mode="json", exclude_unset=True),
            if_match=version,
        )
        return ToolPolicyView.model_validate(written)
