from acme.om.context import TenantContext
from acme.om.exceptions import ValidationFailed
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.types.policy import ToolPolicy
from acme.services.api.services.impl.built import built
from acme.services.api.services.tools import ToolsServiceInterface
from acme.services.api.types.tools import ToolPolicyRequest, ToolPolicyView


class ToolsServiceImpl(ToolsServiceInterface):
    def __init__(self, tools: ToolsManagerInterface) -> None:
        self._tools = tools

    async def get_policy(self, ctx: TenantContext) -> ToolPolicyView:
        return ToolPolicyView.model_validate(await self._tools.get_policy(ctx))

    async def write_policy(
        self, ctx: TenantContext, body: ToolPolicyRequest, version: int | None
    ) -> ToolPolicyView:
        if version is None:
            raise ValidationFailed(
                "a write of the tool policy names the version it read, in If-Match"
            )
        # The manager keeps the stored row's id and provenance; the copy here
        # carries the layer and the version the caller read.
        current = await self._tools.get_policy(ctx)
        policy = built(
            ToolPolicy,
            {**current.model_dump(), **body.model_dump(), "version": version},
        )
        return ToolPolicyView.model_validate(await self._tools.write_policy(ctx, policy))
