"""The API and the session runner of the portal's scene, each the binary a
product's own entry point starts with the ports a product hands it, run by
the browser check and by no gate:

    python services/api/tests/portal_stack.py api --port <port>
    python services/api/tests/portal_stack.py runner

Both register the scene's software engineer and analysis beside the product's
kinds: the platform's own, each in a directory on this host in place of
its container, the software engineer also writing a plan and asking its person.
The software engineer's scene starts two analysis sub-agents, within the tree the
platform's kinds root. The runner runs one loop at a time, since the
scripted model answers every session from one script: so each turn goes
to the session the scene wrote it for, in the order the loops are
claimed. The runner's executor writes the results stream a fresh executor
would, and each bound repository is cloned from a folder of bare
repositories on this host (`PORTAL_REPOSITORIES`, as `portal_check.py
repository` writes one) instead of over HTTPS. The forge is its twin,
which the seed connects."""

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from acme.om.platform_root import ProductKinds
    from acme.services.api.container import AppContainer
    from acme.services.api.settings import ApiSettings

REPO = Path(__file__).resolve().parents[3]


def scene_kinds() -> ProductKinds:
    """The product's kinds, and the scene's software engineer and analysis, each as
    its latest version: the shipped kind whole, its tree and its share
    included, on this host."""
    from acme.infra.agent_workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
    from acme.om.platform_agents.kinds import ANALYSIS_KIND, SOFTWARE_ENGINEER_KIND
    from acme.om.platform_root import ProductKinds
    from acme.om.product_kinds import PRODUCT_KINDS
    from acme.om.tools.native.ask_person import ASK_PERSON
    from acme.om.tools.native.write_agent_plan import WRITE_AGENT_PLAN

    host = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
    software_engineer = SOFTWARE_ENGINEER_KIND.model_copy(
        update={
            "version": SOFTWARE_ENGINEER_KIND.version + 1,
            "isolation": host,
            "tools": (*SOFTWARE_ENGINEER_KIND.tools, WRITE_AGENT_PLAN, ASK_PERSON),
        }
    )
    analysis = ANALYSIS_KIND.model_copy(
        update={"version": ANALYSIS_KIND.version + 1, "isolation": host}
    )
    return ProductKinds(agents=(*PRODUCT_KINDS.agents, software_engineer, analysis))


def scene_container(settings: ApiSettings) -> AppContainer:
    """The API's container over the scene's kinds."""
    from acme.infra.impl.configured import InfraConfiguredImpl
    from acme.integrations.impl.configured import IntegrationsConfiguredImpl
    from acme.om.platform_agents.settings import shipped_agents
    from acme.om.platform_root import PlatformPorts
    from acme.services.api.container import AppContainer, postgres_storage

    return AppContainer.over(
        settings,
        postgres_storage(settings),
        InfraConfiguredImpl(settings),
        IntegrationsConfiguredImpl(settings, settings.environment, settings.is_cloud_environment),
        ports=PlatformPorts(kinds=scene_kinds()),
        platform_agents=shipped_agents(settings, settings.environment),
    )


def api(port: int) -> int:
    import uvicorn

    from acme.services.api.app import create_app
    from acme.services.api.container import boot
    from acme.services.api.main import configure_server_logging, server_options
    from acme.services.api.settings import ApiSettings

    settings = ApiSettings()
    boot(settings)
    configure_server_logging()
    container = scene_container(settings)
    uvicorn.run(create_app(container), host=settings.host, port=port, **server_options(settings))
    return 0


def runner() -> int:
    # The trust store before anything that binds ssl is imported, as the
    # binary's own entry point installs it.
    from acme.infra.trust import install_trust_store

    install_trust_store()
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from acme.infra.agent_workspaces import AgentWorkspaceBase
    from acme.om.agent_sessions.types.agent_session import AgentSession
    from acme.om.agent_workspaces.agent_projects import WorkspaceAgentProjectsInterface
    from acme.om.agent_workspaces.impl.agent_projects import WorkspaceAgentProjectsBoundImpl
    from acme.om.agent_workspaces.types.source import RepositoryBinding
    from acme.om.context import TenantContext
    from acme.om.platform_root import PlatformPorts
    from acme.om.storage.impl.postgres import StoragePostgresImpl
    from acme.workers.agent_session_runner.main import main as run
    from acme.workers.agent_session_runner.settings import AgentSessionRunnerSettings

    from contracts.evidence import ScriptedExecutor

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
            if bound is None:
                return None
            local = bound.repository.replace("https://", f"file://{self._root}/", 1)
            return bound.model_copy(update={"repository": local})

        async def keeps_snapshots(self, ctx: TenantContext, agent_project_id: UUID) -> bool:
            return await self._inner.keeps_snapshots(ctx, agent_project_id)

        async def workspace_base_of(
            self, ctx: TenantContext, agent_project_id: UUID
        ) -> AgentWorkspaceBase | None:
            return await self._inner.workspace_base_of(ctx, agent_project_id)

    # One loop at a time: the script is one queue for every session.
    os.environ["ACME_RUNNER_CAPACITY"] = "1"
    settings = AgentSessionRunnerSettings()
    rows = StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )
    ports = PlatformPorts(
        kinds=scene_kinds(),
        executor=ScriptedExecutor(capabilities=frozenset()),
        workspace_agent_projects=RepositoriesOnDisk(
            WorkspaceAgentProjectsBoundImpl(rows.get_agent_project_storage()),
            Path(os.environ["PORTAL_REPOSITORIES"]),
        ),
    )
    return run(["serve"], ports=ports)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api").add_argument("--port", type=int, required=True)
    commands.add_parser("runner")
    args = parser.parse_args(argv)
    if args.command == "api":
        return api(args.port)
    return runner()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
