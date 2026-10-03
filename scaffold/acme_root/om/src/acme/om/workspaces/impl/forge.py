"""Source control as the forge integration holds it: a session's branch, its
snapshots, and its pull request, written with the integration's own
credential, which never leaves the integration; the commits go to it as the
platform's bundle. The workspaces call it only for a write the
session's push token reaches.

Each write goes through the installation of the forge that holds the bound
repository, and only once the session's own tenant connected it (the
intake's installation-to-tenant mapping, `tenant_of`). A repository no
installation of the tenant's holds is refused, `NotAuthorized`, before
anything is written: one App serves every tenant, and its credential would
reach another tenant's repository. A write the forge refuses is
`ValidationFailed`; one it cannot take now, or with no forge at all, is
`Unavailable`."""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface
from acme.integrations.exceptions import ProviderRefused
from acme.om.context import TenantContext
from acme.om.exceptions import NotAuthorized, PlatformException, Unavailable, ValidationFailed
from acme.om.workspaces.projects import SourceControlInterface
from acme.om.workspaces.types.source import OpenedPullRequest, RepositoryBinding

log = logging.getLogger(__name__)

FORGE = "forge"
"""The integration that holds a session's work."""

TenantOf = Callable[[str, str], Awaitable[UUID | None]]
"""The tenant that connected an integration's installation, None when none
did."""


class SourceControlForgeImpl(SourceControlInterface):
    def __init__(
        self, integration: Callable[[str], IntegrationInterface], tenant_of: TenantOf
    ) -> None:
        self._integration = integration
        self._tenant_of = tenant_of

    async def push(
        self, ctx: TenantContext, binding: RepositoryBinding, ref: str, head: str, bundle: bytes
    ) -> None:
        installation = await self._installation(ctx, binding)
        try:
            await self._integration(FORGE).push(
                binding.repository, ref, head, bundle, installation=installation
            )
        except InfraException as failed:
            raise _failure(f"the forge took no {ref}", failed) from None

    async def open_pull_request(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str, title: str, body: str
    ) -> OpenedPullRequest:
        installation = await self._installation(ctx, binding)
        try:
            opened = await self._integration(FORGE).open_pull_request(
                binding.repository,
                branch,
                binding.default_branch,
                title,
                body,
                installation=installation,
            )
        except InfraException as failed:
            raise _failure(f"the forge opened no pull request of {branch}", failed) from None
        return OpenedPullRequest(id=opened.id, url=opened.url)

    async def _installation(self, ctx: TenantContext, binding: RepositoryBinding) -> str:
        """The installation that holds the bound repository, once the
        session's tenant connected it; `NotAuthorized` otherwise."""
        try:
            installation = await self._integration(FORGE).installation_of(binding.repository)
        except InfraException as failed:
            raise _failure(
                f"the forge named no installation of {binding.repository}", failed
            ) from None
        if await self._tenant_of(FORGE, installation) != ctx.org_id:
            log.warning(
                "org %s: a write to %s was refused: its installation is not the org's",
                ctx.org_id,
                binding.repository,
            )
            raise NotAuthorized(
                f"no installation of the forge this tenant connected holds {binding.repository}"
            )
        return installation


def _failure(what: str, failed: InfraException) -> PlatformException:
    """A refusal is the write's for good; anything else may pass."""
    kind = ValidationFailed if isinstance(failed, ProviderRefused) else Unavailable
    return kind(f"{what}: {failed.message}")


class SourceControlAbsentImpl(SourceControlInterface):
    """No forge is connected: every write is unavailable."""

    async def push(
        self, ctx: TenantContext, binding: RepositoryBinding, ref: str, head: str, bundle: bytes
    ) -> None:
        raise Unavailable("no forge is connected")

    async def open_pull_request(
        self, ctx: TenantContext, binding: RepositoryBinding, branch: str, title: str, body: str
    ) -> OpenedPullRequest:
        raise Unavailable("no forge is connected")
