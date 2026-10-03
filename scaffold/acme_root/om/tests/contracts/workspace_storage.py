"""The workspace storage contract: each session's pinned workspace, each
project's egress allowlist, and the record of a project's fetch
credential. The cases named in `CROSS_TENANT_CASES` are the
tenant fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes."""

from uuid import UUID

import pytest

from acme.infra.workspaces import EgressMode, IsolationMode, ResourceLimits
from acme.om.base import new_id, utcnow
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken
from acme.om.outbox.types.row import OutboxRow
from acme.om.workspaces.storage import WorkspaceStorageInterface
from acme.om.workspaces.types.credential import RepositoryCredential
from acme.om.workspaces.types.egress import EgressAllowlist, EgressMethod, EgressRule
from acme.om.workspaces.types.workspace import SessionWorkspace

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_allowlist",
        "create_credential",
        "create_workspace",
        "purge_credentials",
        "purge_tenant",
        "purge_workspace",
        "read_allowlist",
        "read_credential",
        "read_credentials",
        "read_workspace",
        "write_allowlist",
        "write_credential",
        "write_workspace",
    }
)
"""Every method of `WorkspaceStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""

RULE = EgressRule(destination="registry.example.com", methods=(EgressMethod.GET,))


def make_workspace() -> SessionWorkspace:
    now = utcnow()
    actor = new_id()
    session = new_id()
    return SessionWorkspace(
        id=session,
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        project_id=new_id(),
        level=IsolationMode.CONTAINER,
        limits=ResourceLimits(cpus=2, memory_mb=4096),
        egress=EgressMode.ALLOWLIST,
        rules=(RULE,),
        egress_source="a project's allowlist at version 1",
        branch=f"sessions/{session}",
    )


def make_allowlist(*, project_id: UUID | None = None, open_egress: bool = False) -> EgressAllowlist:
    now = utcnow()
    actor = new_id()
    return EgressAllowlist(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        project_id=project_id or new_id(),
        rules=() if open_egress else (RULE,),
        open=open_egress,
        reason="the build reaches the public internet" if open_egress else None,
    )


class WorkspaceStorageContract:
    @pytest.fixture
    def storage(self) -> WorkspaceStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    @pytest.fixture
    def rows(self) -> tuple[OutboxRow, ...]:
        """The outbox rows an allowlist write lands with: none, unless the
        concrete class can land them."""
        return ()

    # A session's workspace.

    async def test_a_workspace_round_trips(self, storage: WorkspaceStorageInterface) -> None:
        org = new_id()
        workspace = make_workspace()
        assert await storage.read_workspace(org, workspace.id) is None
        assert await storage.create_workspace(org, workspace)
        assert await storage.read_workspace(org, workspace.id) == workspace

    async def test_a_pin_lands_once(self, storage: WorkspaceStorageInterface) -> None:
        org = new_id()
        workspace = make_workspace()
        assert await storage.create_workspace(org, workspace)
        other = workspace.model_copy(update={"level": IsolationMode.TWIN})
        assert not await storage.create_workspace(org, other)
        assert await storage.read_workspace(org, workspace.id) == workspace

    async def test_create_workspace_under_another_tenant_is_not_read_here(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        workspace = make_workspace()
        assert await storage.create_workspace(org_a, workspace)
        assert not await storage.create_workspace(org_b, workspace)
        assert await storage.read_workspace(org_b, workspace.id) is None

    async def test_read_workspace_of_another_tenant_finds_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        workspace = make_workspace()
        assert await storage.create_workspace(new_id(), workspace)
        assert await storage.read_workspace(new_id(), workspace.id) is None

    async def test_write_workspace_is_a_compare_and_set(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org = new_id()
        workspace = make_workspace()
        assert await storage.create_workspace(org, workspace)
        moved = workspace.model_copy(
            update={
                "branch_seen": True,
                "snapshot_ref": f"refs/snapshots/{workspace.branch}/1",
                "notices": ("told", "told again"),
                "push_digest": "d" * 64,
                "push_expires_at": utcnow(),
                "version": 2,
            }
        )
        await storage.write_workspace(org, moved, 1)
        assert await storage.read_workspace(org, workspace.id) == moved
        with pytest.raises(PreconditionFailed):
            await storage.write_workspace(org, moved.model_copy(update={"version": 3}), 1)
        assert await storage.read_workspace(org, workspace.id) == moved

    async def test_write_workspace_of_another_tenant_changes_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        workspace = make_workspace()
        assert await storage.create_workspace(org_a, workspace)
        with pytest.raises(PreconditionFailed):
            await storage.write_workspace(
                org_b, workspace.model_copy(update={"notices": ("x",), "version": 2}), 1
            )
        assert await storage.read_workspace(org_a, workspace.id) == workspace

    # A project's allowlist.

    async def test_an_allowlist_round_trips(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        org = new_id()
        allowlist = make_allowlist()
        assert await storage.read_allowlist(org, allowlist.project_id) is None
        assert await storage.create_allowlist(org, allowlist, rows)
        assert await storage.read_allowlist(org, allowlist.project_id) == allowlist
        opened = make_allowlist(open_egress=True)
        assert await storage.create_allowlist(org, opened, rows)
        assert await storage.read_allowlist(org, opened.project_id) == opened

    async def test_a_project_holds_one_allowlist(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        org = new_id()
        first = make_allowlist()
        assert await storage.create_allowlist(org, first, rows)
        assert not await storage.create_allowlist(org, first, rows)
        with pytest.raises(UniqueKeyTaken):
            await storage.create_allowlist(
                org, make_allowlist(project_id=first.project_id, open_egress=True), rows
            )
        assert await storage.read_allowlist(org, first.project_id) == first

    async def test_create_allowlist_under_another_tenant_is_not_read_here(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        org_a, org_b = new_id(), new_id()
        allowlist = make_allowlist()
        assert await storage.create_allowlist(org_a, allowlist, rows)
        assert await storage.read_allowlist(org_b, allowlist.project_id) is None
        # Another tenant's project of the same id is its own.
        theirs = make_allowlist(project_id=allowlist.project_id, open_egress=True)
        assert await storage.create_allowlist(org_b, theirs, rows)
        assert await storage.read_allowlist(org_a, allowlist.project_id) == allowlist

    async def test_read_allowlist_of_another_tenant_finds_nothing(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        allowlist = make_allowlist()
        assert await storage.create_allowlist(new_id(), allowlist, rows)
        assert await storage.read_allowlist(new_id(), allowlist.project_id) is None

    async def test_write_allowlist_is_a_compare_and_set(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        org = new_id()
        allowlist = make_allowlist()
        assert await storage.create_allowlist(org, allowlist, rows)
        opened = allowlist.model_copy(
            update={"rules": (), "open": True, "reason": "a recorded choice", "version": 2}
        )
        await storage.write_allowlist(org, opened, 1, rows)
        assert await storage.read_allowlist(org, allowlist.project_id) == opened
        with pytest.raises(PreconditionFailed):
            await storage.write_allowlist(org, opened.model_copy(update={"version": 3}), 1, rows)
        assert await storage.read_allowlist(org, allowlist.project_id) == opened

    async def test_write_allowlist_of_another_tenant_changes_nothing(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        org_a, org_b = new_id(), new_id()
        allowlist = make_allowlist()
        assert await storage.create_allowlist(org_a, allowlist, rows)
        with pytest.raises(PreconditionFailed):
            await storage.write_allowlist(
                org_b, allowlist.model_copy(update={"version": 2}), 1, rows
            )
        assert await storage.read_allowlist(org_a, allowlist.project_id) == allowlist

    # The sweep.

    async def test_purge_workspace_takes_the_sessions_row_alone(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org = new_id()
        purged, stays = make_workspace(), make_workspace()
        assert await storage.create_workspace(org, purged)
        assert await storage.create_workspace(org, stays)
        assert await storage.purge_workspace(org, purged.id)
        assert not await storage.purge_workspace(org, purged.id)
        assert await storage.read_workspace(org, purged.id) is None
        assert await storage.read_workspace(org, stays.id) == stays

    async def test_purge_workspace_of_another_tenant_takes_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org = new_id()
        workspace = make_workspace()
        assert await storage.create_workspace(org, workspace)
        assert not await storage.purge_workspace(new_id(), workspace.id)
        assert await storage.read_workspace(org, workspace.id) == workspace

    async def test_purge_tenant_takes_the_tenants_rows_and_no_other(
        self, storage: WorkspaceStorageInterface, rows: tuple[OutboxRow, ...]
    ) -> None:
        gone, kept = new_id(), new_id()
        stays, listed = make_workspace(), make_allowlist()
        assert await storage.create_workspace(gone, make_workspace())
        assert await storage.create_allowlist(gone, make_allowlist(), rows)
        assert await storage.create_workspace(kept, stays)
        assert await storage.create_allowlist(kept, listed, rows)
        assert await storage.purge_tenant(gone, 10) == 2
        assert await storage.purge_tenant(gone, 10) == 0
        assert await storage.read_workspace(kept, stays.id) == stays
        assert await storage.read_allowlist(kept, listed.project_id) == listed


def make_credential(project_id: UUID | None = None) -> RepositoryCredential:
    now, actor = utcnow(), new_id()
    return RepositoryCredential(
        id=project_id or new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
    )


class RepositoryCredentialContract:
    """The record of a project's fetch credential: one a project, under the
    project's id, and the tenant's alone."""

    @pytest.fixture
    def storage(self) -> WorkspaceStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_a_credential_round_trips_once(self, storage: WorkspaceStorageInterface) -> None:
        org = new_id()
        record = make_credential()
        assert await storage.read_credential(org, record.id) is None
        assert await storage.create_credential(org, record)
        assert not await storage.create_credential(org, record.model_copy(update={"version": 5}))
        assert await storage.read_credential(org, record.id) == record
        assert await storage.read_credentials(org, 10) == [record]

    async def test_create_credential_under_another_tenant_is_not_read_here(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        record = make_credential()
        assert await storage.create_credential(org_a, record)
        assert not await storage.create_credential(org_b, record)
        assert await storage.read_credential(org_b, record.id) is None

    async def test_read_credential_of_another_tenant_finds_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        record = make_credential()
        assert await storage.create_credential(new_id(), record)
        assert await storage.read_credential(new_id(), record.id) is None

    async def test_read_credentials_of_another_tenant_finds_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        assert await storage.create_credential(new_id(), make_credential())
        assert await storage.read_credentials(new_id(), 10) == []

    async def test_write_credential_is_a_compare_and_set(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org = new_id()
        record = make_credential()
        assert await storage.create_credential(org, record)
        rotated = record.model_copy(update={"version": 2, "updated_by": new_id()})
        await storage.write_credential(org, rotated, 1)
        assert await storage.read_credential(org, record.id) == rotated
        with pytest.raises(PreconditionFailed):
            await storage.write_credential(org, rotated.model_copy(update={"version": 3}), 1)
        assert await storage.read_credential(org, record.id) == rotated

    async def test_write_credential_of_another_tenant_changes_nothing(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        record = make_credential()
        assert await storage.create_credential(org_a, record)
        with pytest.raises(PreconditionFailed):
            await storage.write_credential(org_b, record.model_copy(update={"version": 2}), 1)
        assert await storage.read_credential(org_a, record.id) == record

    async def test_purge_credentials_takes_the_named_records_of_the_tenant_alone(
        self, storage: WorkspaceStorageInterface
    ) -> None:
        gone, kept = new_id(), new_id()
        first, second, theirs = make_credential(), make_credential(), make_credential()
        assert await storage.create_credential(gone, first)
        assert await storage.create_credential(gone, second)
        assert await storage.create_credential(kept, theirs)
        assert await storage.purge_credentials(gone, [first.id, theirs.id]) == 1
        assert await storage.purge_credentials(gone, []) == 0
        assert await storage.read_credentials(gone, 10) == [second], "only the records named"
        assert await storage.read_credential(kept, theirs.id) == theirs
