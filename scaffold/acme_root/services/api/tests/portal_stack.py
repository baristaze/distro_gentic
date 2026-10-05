"""The API and the session runner of the portal's scene, each the binary a
product's own entry point starts with the ports a product hands it, run by
the browser check and by no gate:

    python services/api/tests/portal_stack.py api --port <port>
    python services/api/tests/portal_stack.py runner

Both register the scene's engineer and analysis beside the product's
kinds: the platform's own, each in a directory on this host in place of
its container, the engineer also writing a plan and asking its person.
The engineer's scene starts two analysis sub-agents, within the tree the
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
    from acme.om.root import ProductKinds
    from acme.services.api.container import AppContainer
    from acme.services.api.settings import ApiSettings

REPO = Path(__file__).resolve().parents[3]


def scene_kinds() -> ProductKinds:
    """The product's kinds, and the scene's engineer and analysis, each as
    its latest version: the shipped kind whole, its tree and its share
    included, on this host."""
    from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
    from acme.om.platform_agents.kinds import ANALYSIS_KIND, ENGINEER_KIND
    from acme.om.product_kinds import PRODUCT_KINDS
    from acme.om.root import ProductKinds
    from acme.om.tools.native.ask_person import ASK_PERSON
    from acme.om.tools.native.write_plan import WRITE_PLAN

    host = IsolationSpec(mode=IsolationMode.HOST, egress=EgressPolicy(mode=EgressMode.OPEN))
    engineer = ENGINEER_KIND.model_copy(
        update={
            "version": ENGINEER_KIND.version + 1,
            "isolation": host,
            "tools": (*ENGINEER_KIND.tools, WRITE_PLAN, ASK_PERSON),
        }
    )
    analysis = ANALYSIS_KIND.model_copy(
        update={"version": ANALYSIS_KIND.version + 1, "isolation": host}
    )
    return ProductKinds(agents=(*PRODUCT_KINDS.agents, engineer, analysis))


def scene_container(settings: ApiSettings) -> AppContainer:
    """The API's container over the scene's kinds."""
    from acme.infra.impl.configured import InfraConfiguredImpl
    from acme.integrations.impl.configured import IntegrationsConfiguredImpl
    from acme.om.platform_agents.settings import shipped_agents
    from acme.om.root import PlatformPorts
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
    from contracts.evidence import ScriptedExecutor

    from acme.om.agent_sessions.types.agent_session import AgentSession
    from acme.om.context import TenantContext
    from acme.om.root import PlatformPorts
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

    # One loop at a time: the script is one queue for every session.
    os.environ["ACME_RUNNER_CAPACITY"] = "1"
    settings = SessionRunnerSettings()
    rows = StoragePostgresImpl(
        settings.role_urls(), settings.role_pools(), system_urls=settings.system_role_urls()
    )
    ports = PlatformPorts(
        kinds=scene_kinds(),
        executor=ScriptedExecutor(capabilities=frozenset()),
        workspace_projects=RepositoriesOnDisk(
            WorkspaceProjectsBoundImpl(rows.get_project_storage()),
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
