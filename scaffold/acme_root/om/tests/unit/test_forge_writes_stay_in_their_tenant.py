"""A forge write goes only through an installation the writing session's own
tenant connected. One App serves every tenant, so its credential reaches
every repository any tenant's installation holds: a session of one tenant
that asks to push, to open a pull request, or to comment on a repository
only another tenant's installation holds is refused, and no write reaches
the forge."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from contracts.intake import APP, Wired, wired

from acme.integrations.events import OpenedPullRequest, PostedMessage
from acme.integrations.events.twin import IntegrationTwinImpl, twin_installation
from acme.om.base import new_id, utcnow
from acme.om.context import CredentialKind, RequestContext, Role, TenantContext, build_context
from acme.om.exceptions import NotAuthorized, ToolFailed
from acme.om.intake.tools import FORGE, CommentImpl, CommentInput
from acme.om.intake.types.link import Installation
from acme.om.steps.types.header import ToolFailure
from acme.om.tenancy.rules import permissions_of
from acme.om.tools.tool import ToolRuntime
from acme.om.workspaces.impl.forge import SourceControlForgeImpl
from acme.om.workspaces.types.source import RepositoryBinding

REPOSITORY = "https://forge.example/beta/widgets.git"
"""The repository the forge's installation of its owner, `beta`, holds."""
ADDRESS = "beta/widgets#12"
HEAD = "9" * 40


class Recording(IntegrationTwinImpl):
    """The forge's twin, recording each write that reaches it, refused or
    not."""

    def __init__(self) -> None:
        super().__init__(FORGE)
        self.writes: list[str] = []

    async def post(
        self, address: str, text: str, mark: str | None = None, *, installation: str | None = None
    ) -> PostedMessage:
        self.writes.append(f"post {address}")
        return await super().post(address, text, mark, installation=installation)

    async def push(
        self, repository: str, ref: str, head: str, bundle: bytes, *, installation: str
    ) -> None:
        self.writes.append(f"push {ref}")
        await super().push(repository, ref, head, bundle, installation=installation)

    async def open_pull_request(
        self,
        repository: str,
        head: str,
        base: str | None,
        title: str,
        body: str,
        *,
        installation: str,
    ) -> OpenedPullRequest:
        self.writes.append(f"pull request {head}")
        return await super().open_pull_request(
            repository, head, base, title, body, installation=installation
        )


def member_of(org_id: UUID) -> TenantContext:
    return build_context(
        RequestContext(request_id=new_id(), app=APP),
        user_id=new_id(),
        org_id=org_id,
        role=Role.MEMBER,
        permissions=permissions_of(Role.MEMBER),
        credential_kind=CredentialKind.SESSION_TOKEN,
    )


@pytest.fixture
async def platform(tmp_path: Path) -> Wired:
    """Tenant A is the platform's owner; another tenant connected the
    forge's installation that holds the repository."""
    return wired(tmp_path)


async def connected_by_another(platform: Wired) -> UUID:
    other = new_id()
    await platform.storage.get_intake_storage().create_installation(
        other,
        Installation(
            id=new_id(),
            created_at=utcnow(),
            integration=FORGE,
            installation=twin_installation("beta"),
            created_by=new_id(),
        ),
    )
    return other


async def test_a_push_or_a_pull_request_on_another_tenants_repository_is_refused(
    platform: Wired,
) -> None:
    other = await connected_by_another(platform)
    forge = Recording()
    writes = SourceControlForgeImpl(
        lambda name: forge, platform.storage.get_intake_storage().read_installation_org
    )
    binding = RepositoryBinding(project_id=new_id(), repository=REPOSITORY)

    with pytest.raises(NotAuthorized, match="no installation of the forge this tenant connected"):
        await writes.push(platform.owner, binding, "refs/heads/agent/x", HEAD, b"")
    with pytest.raises(NotAuthorized, match="no installation of the forge this tenant connected"):
        await writes.open_pull_request(platform.owner, binding, "agent/x", "T", "B")
    assert forge.writes == [] and forge.refs == {} and forge.pull_requests == []

    # The tenant that connected the installation writes through it.
    theirs = member_of(other)
    await writes.push(theirs, binding, "refs/heads/agent/x", HEAD, b"")
    opened = await writes.open_pull_request(theirs, binding, "agent/x", "T", "B")
    assert forge.writes == ["push refs/heads/agent/x", "pull request agent/x"]
    assert opened.url.endswith("/pull/1")


async def test_a_comment_on_another_tenants_repository_is_refused_before_anything_is_recorded(
    platform: Wired,
) -> None:
    await connected_by_another(platform)
    forge = Recording()
    tool = CommentImpl(lambda: platform.intake, lambda name: forge)
    session_id, key = new_id(), new_id()
    runtime = cast(ToolRuntime, SimpleNamespace(session_id=session_id, key=key))

    with pytest.raises(ToolFailed) as refused:
        await tool.run(platform.owner, CommentInput(on=ADDRESS, text="Fixed."), runtime)
    assert refused.value.failure is ToolFailure.DENIED
    assert forge.writes == [] and forge.posted == []
    intake = platform.storage.get_intake_storage()
    assert await intake.read_act(platform.owner.org_id, FORGE, (str(key),)) is None
