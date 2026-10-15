"""The runner boots the way every process does: settings, storage, infra,
the integrations (the model providers), and the managers, with the
product's agent kinds and tools. The claim loop holds the container
directly.

The runner holds no purge login: it runs what a model asks for, and the
one login that deletes a history is the maintenance worker's alone."""

import logging

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.integrations.impl.configured import IntegrationsConfiguredImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.settings import shipped_agents
from acme.om.platform_root import PlatformManagers, PlatformPorts
from acme.om.product_kinds import PRODUCT_KINDS
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.attachments import AttachmentReaderInterface
from acme.workers.session_runner.platform.container import RunnerPlatform, build_runner_platform
from acme.workers.session_runner.settings import SessionRunnerSettings

log = logging.getLogger(__name__)


class RunnerContainer:
    def __init__(
        self,
        settings: SessionRunnerSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        managers: PlatformManagers,
        platform: RunnerPlatform,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.integrations = integrations
        self.managers = managers
        self.platform = platform

    @classmethod
    def build(
        cls,
        settings: SessionRunnerSettings,
        *,
        attachment_reader: AttachmentReaderInterface | None = None,
        ports: PlatformPorts | None = None,
    ) -> RunnerContainer:
        """Over the database, the infra, and the providers the settings
        name. `attachment_reader` reads an attachment's text for the
        engine's read tool, and None refuses every read. `ports` are the
        product's, among them the evidence's executor and work product;
        None hands the root `PRODUCT_KINDS` and the platform's own ports,
        and a product that sets ports of its own sets `kinds=PRODUCT_KINDS`
        among them, so every process knows the same kinds."""
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        integrations = IntegrationsConfiguredImpl(
            settings, settings.environment, settings.is_cloud_environment
        )
        return cls.over(
            settings,
            storage,
            infra,
            integrations,
            attachment_reader=attachment_reader,
            ports=ports or PlatformPorts(kinds=PRODUCT_KINDS),
            platform_agents=shipped_agents(settings, settings.environment),
        )

    @classmethod
    def over(
        cls,
        settings: SessionRunnerSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        *,
        attachment_reader: AttachmentReaderInterface | None = None,
        ports: PlatformPorts | None = None,
        platform_agents: PlatformAgents | None = None,
        placement_options: PlacementOptions | None = None,
    ) -> RunnerContainer:
        """The managers over whichever roots the caller chose: the platform's,
        as `platform.container.build_runner_platform` builds them with `ports`,
        `platform_agents`, and `placement_options`."""
        managers, platform = build_runner_platform(
            settings,
            storage,
            infra,
            integrations,
            attachment_reader=attachment_reader,
            ports=ports,
            platform_agents=platform_agents,
            placement_options=placement_options,
        )
        return cls(settings, storage, infra, integrations, managers, platform)

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.runner_id,
            ", ".join([*self.infra.describe(), *self.integrations.describe()]),
        )

    async def close(self) -> None:
        await self.platform.close()
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
