from uuid import UUID

from acme.om.context import TenantContext
from acme.om.retention import RetentionManagerInterface
from acme.om.retention.types.policy import TenantRetention
from acme.services.api.services.impl.built import built
from acme.services.api.services.retention import RetentionServiceInterface
from acme.services.api.types.retention import (
    RetentionRequest,
    RetentionView,
    SessionRetentionView,
)


class RetentionServiceImpl(RetentionServiceInterface):
    def __init__(self, retention: RetentionManagerInterface) -> None:
        self._retention = retention

    async def get_policy(self, ctx: TenantContext) -> RetentionView:
        return RetentionView.model_validate(await self._retention.get_policy(ctx))

    async def write_policy(
        self, ctx: TenantContext, body: RetentionRequest, version: int | None
    ) -> RetentionView:
        # The manager keeps the stored row's id and provenance; the copy here
        # carries the policy and the version the caller read, 0 for none. A
        # field left out takes the policy's default, which narrows nothing.
        current = await self._retention.get_policy(ctx)
        policy = built(
            TenantRetention,
            {**current.model_dump(), **body.model_dump(exclude_none=True), "version": version or 0},
        )
        return RetentionView.model_validate(await self._retention.write_policy(ctx, policy))

    async def erase_content(self, ctx: TenantContext, session_id: UUID) -> SessionRetentionView:
        return SessionRetentionView.model_validate(
            await self._retention.erase_content(ctx, session_id)
        )
