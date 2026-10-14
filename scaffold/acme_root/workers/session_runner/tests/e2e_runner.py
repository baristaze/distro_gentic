"""The session runner's binary with the end-to-end suite's kinds and the
platform's ports a product hands it, as a product's own entry point passes
them: the same `main`, run as a process of its own over the compose stack.

    python workers/session_runner/tests/e2e_runner.py serve

The suite names a corpus root, so the platform's agents and their tools
ship, its `run_command` among them. The ports stand in for what a product
brings: an executor that writes the results stream a fresh executor would,
and each bound repository cloned from a folder of bare repositories on
this host (`E2E_REPOSITORIES`) instead of over HTTPS.

With `E2E_CONTAINERS` set, the platform's software engineer is the latest, in its
own container, and no session has a checkout: a container reaches no
folder of this host's."""

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
    from runner_support import E2E_KINDS, KINDS

    from acme.infra.workspaces import WorkspaceBase
    from acme.om.agent_sessions.types.agent_session import AgentSession
    from acme.om.agent_workspaces.agent_projects import WorkspaceAgentProjectsInterface
    from acme.om.agent_workspaces.impl.agent_projects import WorkspaceAgentProjectsBoundImpl
    from acme.om.agent_workspaces.types.source import RepositoryBinding
    from acme.om.context import TenantContext
    from acme.om.root import PlatformPorts, ProductKinds
    from acme.om.storage.impl.postgres import StoragePostgresImpl
    from acme.workers.session_runner.main import main as run
    from acme.workers.session_runner.settings import SessionRunnerSettings

    class RepositoriesOnDisk(WorkspaceAgentProjectsInterface):
        """The agent projects' answers, each bound repository cloned from
        `<root>/<host>/<path>.git` on this host instead of over HTTPS."""

        def __init__(self, inner: WorkspaceAgentProjectsInterface, root: Path) -> None:
            self._inner = inner
            self._root = root

        async def agent_project_of(self, ctx: TenantContext, session: AgentSession) -> UUID | None:
            return await self._inner.agent_project_of(ctx, session)

        async def binding_of(
            self, ctx: TenantContext, agent_project_id: UUID
        ) -> RepositoryBinding | None:
            bound = await self._inner.binding_of(ctx, agent_project_id)
            if bound is None or containers:
                return None
            local = bound.repository.replace("https://", f"file://{self._root}/", 1)
            return bound.model_copy(update={"repository": local})

        async def keeps_snapshots(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
            return await self._inner.keeps_snapshots(ctx, agent_project_id)

        async def workspace_base_of(
            self, ctx: TenantContext, agent_project_id: UUID
        ) -> WorkspaceBase | None:
            return await self._inner.workspace_base_of(ctx, agent_project_id)

    containers = bool(os.environ.get("E2E_CONTAINERS"))
    settings = SessionRunnerSettings()
    rows = StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )
    ports = PlatformPorts(
        kinds=ProductKinds(agents=KINDS if containers else E2E_KINDS),
        executor=ScriptedExecutor(capabilities=frozenset()),
        workspace_agent_projects=RepositoriesOnDisk(
            WorkspaceAgentProjectsBoundImpl(rows.get_agent_project_storage()),
            Path(os.environ["E2E_REPOSITORIES"]),
        ),
    )
    return run(ports=ports)


if __name__ == "__main__":
    sys.exit(main())
