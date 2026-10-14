"""The worker boots the same way a service does: settings, storage, infra,
the integrations (the identity provider), and managers.
The loop holds the container directly."""

import logging
from collections.abc import Callable
from datetime import timedelta

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.integrations.identity import IdentityProviderInterface
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsConfiguredImpl, IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_billing.root import build_money_gate, refuse_open_money
from acme.om.agent_sessions.impl.manager import AgentSessionsOptions
from acme.om.agents.impl.manager import AgentsOptions
from acme.om.attribution.impl.manager import AttributionOptions
from acme.om.budgets.impl.manager import BudgetsOptions
from acme.om.events.impl.manager import EventsOptions
from acme.om.idempotency.impl.manager import IdempotencyOptions
from acme.om.intake import IntakeManagerInterface
from acme.om.intake.tools import CommentImpl
from acme.om.leases.impl.manager import LeasesOptions
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.root import MatrixLayer
from acme.om.media.impl.manager import MediaOptions
from acme.om.models.impl.manager import ModelsOptions
from acme.om.orchestrations.impl.manager import OrchestrationsOptions
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.settings import shipped_agents
from acme.om.platform_root import (
    PlatformManagers,
    PlatformPorts,
    ProductKinds,
    build_platform_managers,
    intake_absent,
)
from acme.om.product_kinds import PRODUCT_KINDS
from acme.om.steps.impl.manager import StepsOptions
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.impl.manager import TenancyOptions
from acme.om.tools.impl.manager import ToolsOptions
from acme.om.work.impl.manager import WorkOptions
from acme.workers.maintenance.platform import WorkerPlatform, worker_platform_options
from acme.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)

MEDIA_PURGE_BATCH = 100
"""Files one media purge erases. Each is an object deleted from the store, one
request apiece, before its row, so the batch is smaller than the rows'."""

AGENT_SESSION_PURGE_BATCH = 100
"""Sessions one purge across tenants takes up. Each costs a claim, a batch of
its history, and its row, three statements apiece, so the batch is smaller
than the rows'."""

LEASE_SWEEP_BATCH = LeasesOptions().sweep_batch
"""Leases and requests one org's lease sweep ends; a sweep that ends as many
or more may have left some due."""


def events_options(settings: MaintenanceSettings) -> EventsOptions:
    """The sweep's trim of each living org's stream, 90 days by default and
    off at 0, a batch per call like every purge."""
    days = settings.event_retention_days
    return EventsOptions(
        retention=timedelta(days=days) if days else None, purge_batch=settings.worker_purge_batch
    )


def worker_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    integrations: IntegrationsInterface,
    settings: MaintenanceSettings,
    ports: PlatformPorts | None = None,
    *,
    platform_agents: PlatformAgents | None = None,
    intake: Callable[[], IntakeManagerInterface] = intake_absent,
) -> PlatformManagers:
    """The managers, each one the sweep purges through with its retention and
    its batch from the settings. The worker is the one process that purges,
    so it is the one that sets them. Its budget gate is agent billing's money
    gate, the one whose holds its sweep settles; `ports` are the platform's
    ports the product sets, None each for the platform's own, and their
    `kinds` the product's, which `build` reads from `PRODUCT_KINDS`. Outside
    `local`, a quiet null for any of them, or a budget gate that is not the
    money gate, is refused at boot.

    The catalog classes every tool a session can name, as the API's and the
    session runner's do, since an intake event, an agent automation's start,
    and a message are checked against a session's tools here:
    `platform_agents` ships the platform's agents, which a deployed worker
    reads from its corpus root and refuses to boot with none, and the
    runner's `comment` answers `intake`, the one the container builds over
    these managers."""
    batch = settings.worker_purge_batch
    ports = ports or PlatformPorts()
    # The matrix's face over the models manager, so the purge's models step
    # takes a deleted tenant's pins and choices of fill before its fill sets.
    matrix = MatrixLayer(
        storage,
        options=MatrixOptions(environment=settings.environment, purge_batch=batch),
        kinds=ports.kinds.agents,
    )
    managers = build_platform_managers(
        storage,
        infra,
        TenancyOptions(
            retention=timedelta(days=settings.tenancy_retention_days),
            ticket_retention=timedelta(hours=settings.socket_ticket_retention_hours),
            sign_in_delay_retention=timedelta(hours=settings.sign_in_delay_retention_hours),
            purge_batch=batch,
        ),
        integrations=integrations,
        environment=settings.environment,
        media_options=MediaOptions(
            retention=timedelta(days=settings.media_retention_days),
            pending_expiry=timedelta(hours=settings.media_pending_expiry_hours),
            purge_batch=MEDIA_PURGE_BATCH,
        ),
        idempotency_options=IdempotencyOptions(
            retention=timedelta(hours=settings.idempotency_retention_hours), purge_batch=batch
        ),
        events_options=events_options(settings),
        work_options=WorkOptions(
            retention=timedelta(days=settings.work_retention_days), purge_batch=batch
        ),
        orchestrations_options=OrchestrationsOptions(purge_batch=batch),
        leases_options=LeasesOptions(purge_batch=batch),
        steps_options=StepsOptions(purge_batch=batch),
        agent_sessions_options=AgentSessionsOptions(
            purge_batch=batch,
            retention=timedelta(days=settings.agent_session_retention_days),
            purge_sessions=AGENT_SESSION_PURGE_BATCH,
        ),
        agents_options=AgentsOptions(purge_batch=batch),
        attribution_options=AttributionOptions(purge_batch=batch),
        budgets_options=BudgetsOptions(purge_batch=batch),
        models_options=ModelsOptions(purge_batch=batch),
        tools_options=ToolsOptions(purge_batch=batch),
        tool_catalog=(CommentImpl(intake, integrations.get_integration),),
        budget_gate=ports.budget_gate or build_money_gate(storage),
        result_gate=ports.result_gate,
        models_layer=matrix.layer,
        platform_root_options=worker_platform_options(settings, storage, ports, platform_agents),
    )
    refuse_open_money(settings.environment, managers)
    return managers


class WorkerContainer:
    def __init__(
        self,
        settings: MaintenanceSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: PlatformManagers,
        integrations: IntegrationsInterface,
        kinds: ProductKinds | None = None,
    ) -> None:
        """`kinds` are the product's; None adds none."""
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.integrations = integrations
        self.platform = WorkerPlatform(
            settings, storage, infra, managers, integrations, kinds or ProductKinds()
        )

    @property
    def identity_provider(self) -> IdentityProviderInterface:
        return self.integrations.get_identity_provider()

    @classmethod
    def build(cls, settings: MaintenanceSettings) -> WorkerContainer:
        # The worker is the one process that purges a history, so the one
        # that holds the purge login; it refuses to start without its URL.
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
            purge_urls=settings.purge_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        # The worker signs nobody in. It deletes a deleted account's person,
        # and a deleted org's organization, at the identity provider, so it
        # holds it, refused as the API's is.
        integrations = IntegrationsConfiguredImpl(
            settings, settings.environment, settings.is_cloud_environment
        )
        held: list[WorkerContainer] = []
        managers = worker_managers(
            storage,
            infra,
            integrations,
            settings,
            PlatformPorts(kinds=PRODUCT_KINDS),
            platform_agents=shipped_agents(settings, settings.environment),
            intake=lambda: held[0].platform.intake,
        )
        container = cls(settings, storage, infra, managers, integrations, PRODUCT_KINDS)
        held.append(container)
        return container

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
        integrations: IntegrationsInterface | None = None,
        *,
        ports: PlatformPorts | None = None,
        platform_agents: PlatformAgents | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {"_env_file": None, "environment": "test", "worker_id": "maintenance-test"}
        )
        integrations = integrations or IntegrationsOverImpl(
            IdentityProviderTwinImpl(), absent_model_providers()
        )
        held: list[WorkerContainer] = []
        managers = worker_managers(
            storage,
            infra,
            integrations,
            settings,
            ports,
            platform_agents=platform_agents,
            intake=lambda: held[0].platform.intake,
        )
        kinds = None if ports is None else ports.kinds
        container = cls(settings, storage, infra, managers, integrations, kinds)
        held.append(container)
        return container

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        log.info(
            "%s %s started with %s",
            self.settings.service_name,
            self.settings.worker_id,
            ", ".join([*self.infra.describe(), *self.integrations.describe()]),
        )

    async def close(self) -> None:
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
