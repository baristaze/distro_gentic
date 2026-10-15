"""The handler of a member who left a team org, by their removal or their
account's deletion, while the org stays: it unlinks every outside account
linked to them there. A rerun finds none left."""

import logging
from typing import ClassVar

from acme.om.context import Permission, TenantContext
from acme.om.intake import IntakeManagerInterface
from acme.om.work.types.handler import WorkHandlerInterface
from acme.om.work.types.work_item import WorkItem

log = logging.getLogger(__name__)


class MemberLeftHandlerImpl(WorkHandlerInterface):
    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.MANAGE_MEMBERS,)
    """Unlinking another person's account manages members."""

    def __init__(self, intake: IntakeManagerInterface) -> None:
        self._intake = intake

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        gone = await self._intake.forget_member(ctx, item.target_id)
        log.info("org %s: %d identity links of a departed member are gone", ctx.org_id, gone)
