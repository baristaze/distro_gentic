"""The handler that runs a validation session: the platform's work its start
asked for, with no agent and no model call. The session's check runs on a
fresh executor, and the session finishes with the execution record that run
wrote (`PlatformAgentsManagerInterface.run_validation`).

It is idempotent: a finished session runs nothing, and a run the evidence
kept is never run again. A check its project cannot run, such as one its
policy no longer declares, or one its starter may no longer run, fails for
good; anything else, such as an instance that could not be made, is tried
again."""

import logging
from typing import ClassVar

from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, PreconditionFailed
from acme.om.platform_agents import PlatformAgentsManagerInterface
from acme.om.work.types.handler import WorkHandlerInterface, WorkRefused
from acme.om.work.types.work_item import WorkItem

log = logging.getLogger(__name__)


class ValidationHandlerImpl(WorkHandlerInterface):
    """A validation session's check: run (its declared trials when rated),
    and the session finished."""

    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.WRITE,)
    """`run_validation` writes the session's validation and finishes it."""

    def __init__(self, platform_agents: PlatformAgentsManagerInterface) -> None:
        self._platform_agents = platform_agents

    async def handle(self, ctx: TenantContext, item: WorkItem) -> None:
        try:
            session = await self._platform_agents.run_validation(ctx, item.target_id)
        except NotFound:
            log.info("validation session %s is gone; %s has nothing to do", item.target_id, item.id)
            return
        except PreconditionFailed as refused:
            raise WorkRefused(refused.message) from None
        log.info(
            "validation session %s in org %s finished with run %s",
            session.id,
            ctx.org_id,
            session.run_id,
        )
