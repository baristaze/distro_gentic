"""The handler that runs a validation session: the platform's work its start
asked for, with no agent and no model call. The session's check runs on a
fresh executor, and the session finishes with the execution record that run
wrote (`PlatformAgentsManagerInterface.run_validation`).

It is idempotent: a finished session runs nothing, and a run the evidence
kept is never run again. A check its agent project cannot run, such as one its
policy no longer declares, or one its starter may no longer run, fails for
good, and its session reads refused with the reason. Anything else, such as
an instance that could not be made, is tried again; on the item's last
attempt the session reads refused with the error's class, and the item
still fails for good, so the person who started it reads an end."""

import logging
from typing import ClassVar

from acme.om.context import Permission, TenantContext
from acme.om.exceptions import NotFound, PreconditionFailed
from acme.om.platform_agents import PlatformAgentsManagerInterface
from acme.om.work.rules import is_exhausted
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
        except Exception as error:
            if is_exhausted(item):
                await self._give_up(ctx, item, error)
            raise  # the queue retries the item, or fails it for good on its last attempt
        log.info(
            "validation session %s in org %s finished with run %s",
            session.id,
            ctx.org_id,
            session.run_id,
        )

    async def _give_up(self, ctx: TenantContext, item: WorkItem, error: Exception) -> None:
        """The item's last attempt failed: the session is refused with the
        error's class, never its text, which is not the platform's. A
        refusal that cannot be written is logged, and the item fails for
        good either way."""
        reason = f"its check failed on its last attempt: {type(error).__name__}"
        try:
            await self._platform_agents.refuse_validation(ctx, item.target_id, reason)
        except NotFound, PreconditionFailed:
            return  # gone, or finished meanwhile: nothing waits on it
        except Exception:
            log.exception("validation session %s was not refused after %s", item.target_id, item.id)
            return
        log.warning(
            "validation session %s in org %s refused: %s", item.target_id, ctx.org_id, reason
        )
