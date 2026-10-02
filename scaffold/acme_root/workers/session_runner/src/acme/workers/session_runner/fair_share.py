"""The guard a claimed loop meets before it runs: its tenant's fair share.

A loop over its tenant's share is not a failure. It goes back to its lane
for the delay placement names, with no attempt spent, the way any guard
parks its item (`WorkParked`), and the claim after that delay asks again.
The claim itself stays the guideline's, so the order within a lane does
too."""

from typing import ClassVar

from acme.om.context import Permission, TenantContext
from acme.om.placement import PlacementManagerInterface
from acme.om.work.types.handler import WorkHandlerInterface, WorkParked
from acme.om.work.types.work_item import WorkItem


class FairShareGuardImpl(WorkHandlerInterface):
    """Runs the handler it guards only once placement admits the item."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.READ,)
    """The guard's own read of its tenant's claimed loops. The handler it
    guards declares its own, and the run takes both."""

    def __init__(self, guarded: WorkHandlerInterface, placement: PlacementManagerInterface) -> None:
        self._guarded = guarded
        self._placement = placement

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        wait = await self._placement.admit(ctx, item)
        if wait is not None:
            raise WorkParked("its tenant runs as many loops as its share allows", wait)
        await self._guarded.handle(ctx, item)
