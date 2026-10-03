"""Source control as the forge integration holds it: a session's branch and
its pull request, written with the integration's own credential, which
never leaves the integration. The workspaces call it only for a write the
session's push token reaches. A write the forge refuses is
`ValidationFailed`; one it cannot take now, or with no forge at all, is
`Unavailable`."""

from collections.abc import Callable

from acme.infra.exceptions import InfraException
from acme.integrations.events import IntegrationInterface
from acme.integrations.exceptions import ProviderRefused
from acme.om.exceptions import PlatformException, Unavailable, ValidationFailed
from acme.om.workspaces.projects import SourceControlInterface
from acme.om.workspaces.types.source import OpenedPullRequest, RepositoryBinding

FORGE = "forge"
"""The integration that holds a session's work."""


class SourceControlForgeImpl(SourceControlInterface):
    def __init__(self, integration: Callable[[str], IntegrationInterface]) -> None:
        self._integration = integration

    async def push_branch(self, binding: RepositoryBinding, branch: str, head: str) -> None:
        try:
            await self._integration(FORGE).push_branch(binding.repository, branch, head)
        except InfraException as failed:
            raise _failure(f"the forge took no branch {branch}", failed) from None

    async def open_pull_request(
        self, binding: RepositoryBinding, branch: str, title: str, body: str
    ) -> OpenedPullRequest:
        try:
            opened = await self._integration(FORGE).open_pull_request(
                binding.repository, branch, binding.default_branch, title, body
            )
        except InfraException as failed:
            raise _failure(f"the forge opened no pull request of {branch}", failed) from None
        return OpenedPullRequest(id=opened.id, url=opened.url)


def _failure(what: str, failed: InfraException) -> PlatformException:
    """A refusal is the write's for good; anything else may pass."""
    kind = ValidationFailed if isinstance(failed, ProviderRefused) else Unavailable
    return kind(f"{what}: {failed.message}")


class SourceControlAbsentImpl(SourceControlInterface):
    """No forge is connected: every write is unavailable."""

    async def push_branch(self, binding: RepositoryBinding, branch: str, head: str) -> None:
        raise Unavailable("no forge is connected")

    async def open_pull_request(
        self, binding: RepositoryBinding, branch: str, title: str, body: str
    ) -> OpenedPullRequest:
        raise Unavailable("no forge is connected")
