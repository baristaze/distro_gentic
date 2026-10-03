"""The runner's duty to the instances its host holds: one no run accounts
for is let go.

A run that dies mid-loop never releases its workspace, so its instance
would run on for good. Each pass reads what this host's provider holds,
whichever process prepared it. An instance whose session has a loop item
queued or claimed is a run's, or soon will be, and is left alone: a live
run always holds its loop item claimed. One no run accounts for is let go
once a pass finds it so past a grace, which a follow-up still reattaches
within. It goes through the release a run makes, under its tenant's
context: what its checkout holds is pushed to a snapshot ref first, and a
push that does not land lets nothing go, so the next pass tries again.

An instance is purged only on proof that nothing is left to keep its
work for: its tenant's org row marks it deleted. One whose tenant this
database holds no row of, or whose session it holds no history of, is
left alone and logged: after a restore to an earlier point, it may hold
the only copy of its work. A session marked deleted keeps its history
and may come back, so its instance is released like any other."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field

from acme.infra.workspaces import HeldInstance, Workspace, WorkspaceProviderInterface
from acme.om.base import EMPTY_UUID, Platform, utcnow
from acme.om.context import RequestContext, TenantContext
from acme.om.steps import StepsManagerInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.work import WorkManagerInterface
from acme.om.work.types.work_item import WorkKind
from acme.om.workspaces.manager import WorkspacesManagerInterface

log = logging.getLogger(__name__)


class HeldOptions(Platform):
    # How long an instance no run accounts for stays, counted from the first
    # pass that finds it so, before it is let go.
    grace: timedelta = Field(default=timedelta(minutes=5), gt=timedelta(0))


class HeldWorkspacesSweep:
    """Lets go of each instance this host holds that no run accounts for,
    once a pass finds it so past the grace. When a pass first found each
    one so is held in memory: a runner that restarts counts the grace
    again, so it lets go later, never sooner."""

    def __init__(
        self,
        provider: WorkspaceProviderInterface,
        tools: ToolsManagerInterface,
        workspaces: WorkspacesManagerInterface,
        steps: StepsManagerInterface,
        work: WorkManagerInterface,
        tenancy: TenancyManagerInterface,
        options: HeldOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._workspaces = workspaces
        self._steps = steps
        self._work = work
        self._tenancy = tenancy
        self._options = options
        self._clock = clock
        # Each instance no run accounted for at a pass, and when a pass first
        # found it so.
        self._unaccounted: dict[UUID, datetime] = {}
        # Each instance logged as one this database holds no record of.
        self._logged: set[UUID] = set()

    async def __call__(self, rctx: RequestContext) -> int:
        """One pass over what this host holds; returns how many it let go."""
        held = await self._provider.held()
        now = self._clock()
        ids = {instance.id for instance in held}
        self._unaccounted = {id_: at for id_, at in self._unaccounted.items() if id_ in ids}
        self._logged &= ids
        let_go = 0
        for instance in held:
            try:
                if await self._let_go(rctx, instance, now):
                    let_go += 1
            except Exception:
                log.exception(
                    "the instance of session %s of org %s waits for the next pass",
                    instance.id,
                    instance.org_id,
                )
        return let_go

    async def _let_go(self, rctx: RequestContext, instance: HeldInstance, now: datetime) -> bool:
        """Lets one instance go when no run accounts for it past the grace;
        False when it stays. A failed push raises, and it stays."""
        deleted = await self._tenancy.tenant_deleted(rctx, instance.org_id)
        if deleted is None:
            self._unknown(instance, "its tenant")
            return False
        ctx: TenantContext | None = None
        if not deleted:
            # The platform lets it go, as no person: the system user.
            ctx = await self._tenancy.service_context(rctx, instance.org_id, EMPTY_UUID)
            if await self._work.has_open(ctx, WorkKind.LOOP, instance.id):
                self._unaccounted.pop(instance.id, None)
                return False
        since = self._unaccounted.setdefault(instance.id, now)
        if now - since < self._options.grace:
            return False
        if ctx is None:
            await self._tools.purge_workspace(instance.org_id, instance.id)
            log.info(
                "session %s of org %s: its tenant is deleted, and its instance is purged",
                instance.id,
                instance.org_id,
            )
        elif (await self._steps.get_cursor(ctx, instance.id)).epoch == 0:
            # A run took an epoch before it prepared this instance, so a
            # session with none here is one this database has no history of.
            self._unknown(instance, "its session")
            return False
        else:
            pinned = await self._workspaces.get_workspace(ctx, instance.id)
            workspace = Workspace(
                id=instance.id,
                org_id=instance.org_id,
                spec=pinned.spec(),
                location=instance.location,
            )
            await self._tools.release_workspace(ctx, workspace)
            log.info(
                "session %s of org %s: its instance no run held is released",
                instance.id,
                instance.org_id,
            )
        self._unaccounted.pop(instance.id, None)
        return True

    def _unknown(self, instance: HeldInstance, what: str) -> None:
        """Logs, once a process, an instance this database cannot account
        for, which stays."""
        if instance.id in self._logged:
            return
        self._logged.add(instance.id)
        log.warning(
            "session %s of org %s: this database holds no record of %s, so its "
            "instance at %s is left as it is",
            instance.id,
            instance.org_id,
            what,
            instance.location,
        )
