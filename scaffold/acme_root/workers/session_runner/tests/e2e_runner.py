"""The session runner's binary with the end-to-end suite's kinds and the
platform's ports a product hands it, as a product's own entry point passes
them: the same `main`, run as a process of its own over the compose stack.

    python workers/session_runner/tests/e2e_runner.py serve

The suite names a corpus root, so the platform's agents and their tools
ship, its `run_command` among them. The ports stand in for what a product
brings: an executor that writes the results stream a fresh executor would,
and each bound repository cloned from a folder of bare repositories on
this host (`E2E_REPOSITORIES`) instead of over HTTPS."""

import os
import sys
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[3]


def main() -> int:
    # The trust store before anything that binds ssl is imported, as the
    # binary's own entry point installs it.
    from acme.infra.trust import install_trust_store

    install_trust_store()
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from contracts.evidence import ScriptedExecutor
    from runner_support import E2E_KINDS

    from acme.om.agent_sessions.types.agent_session import AgentSession
    from acme.om.context import TenantContext
    from acme.om.root import PlatformPorts, ProductKinds
    from acme.om.storage.impl.postgres import StoragePostgresImpl
    from acme.om.workspaces.impl.projects import WorkspaceProjectsBoundImpl
    from acme.om.workspaces.projects import WorkspaceProjectsInterface
    from acme.om.workspaces.types.source import RepositoryBinding
    from acme.workers.session_runner.main import main as run
    from acme.workers.session_runner.settings import SessionRunnerSettings

    class RepositoriesOnDisk(WorkspaceProjectsInterface):
        """The projects' answers, each bound repository cloned from
        `<root>/<host>/<path>.git` on this host instead of over HTTPS."""

        def __init__(self, inner: WorkspaceProjectsInterface, root: Path) -> None:
            self._inner = inner
            self._root = root

        async def project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
            return await self._inner.project_of(ctx, session)

        async def binding_of(
            self, ctx: TenantContext, project_id: UUID
        ) -> RepositoryBinding | None:
            bound = await self._inner.binding_of(ctx, project_id)
            if bound is None:
                return None
            local = bound.repository.replace("https://", f"file://{self._root}/", 1)
            return bound.model_copy(update={"repository": local})

    settings = SessionRunnerSettings()
    rows = StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )
    ports = PlatformPorts(
        kinds=ProductKinds(agents=E2E_KINDS),
        executor=ScriptedExecutor(capabilities=frozenset()),
        workspace_projects=RepositoriesOnDisk(
            WorkspaceProjectsBoundImpl(rows.get_project_storage()),
            Path(os.environ["E2E_REPOSITORIES"]),
        ),
    )
    return run(ports=ports)


if __name__ == "__main__":
    sys.exit(main())
