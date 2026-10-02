"""The worker boots the same way a service does: settings, storage, infra,
the integrations (the identity provider), and managers.
The loop holds the container directly."""

import logging
from datetime import timedelta

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.root import InfraInterface
from acme.integrations.identity import IdentityProviderInterface
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.impl.configured import IntegrationsConfiguredImpl, IntegrationsOverImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_sessions.impl.manager import AgentSessionsOptions
from acme.om.agents.impl.manager import AgentsOptions
from acme.om.attribution.impl.manager import AttributionOptions
from acme.om.automations.impl.manager import AutomationsOptions
from acme.om.automations.root import build_automations
from acme.om.base import new_id
from acme.om.billing.impl.sweep import HoldSweepImpl, HoldSweepOptions
from acme.om.billing.sweep import ProviderBillsUnknownImpl
from acme.om.budgets.impl.manager import BudgetsOptions
from acme.om.events.impl.manager import EventsOptions
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.idempotency.impl.manager import IdempotencyOptions
from acme.om.intake.impl.manager import IntakeOptions
from acme.om.intake.root import build_intake
from acme.om.knowledge.impl.manager import KnowledgeOptions
from acme.om.knowledge.root import build_knowledge
from acme.om.media.impl.manager import MediaOptions
from acme.om.models.impl.manager import ModelsOptions
from acme.om.orchestrations.impl.manager import OrchestrationsOptions
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.platform_agents.impl.manager import PlatformAgentsOptions
from acme.om.playbooks.impl.manager import PlaybooksOptions
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.projects.impl.manager import ProjectsOptions
from acme.om.retention.impl.manager import RetentionOptions
from acme.om.root import Managers, build_managers
from acme.om.steps.impl.manager import StepsOptions
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.impl.manager import TenancyOptions
from acme.om.tools.impl.manager import ToolsOptions
from acme.om.trust.impl.keys import KeyProbeAbsentImpl
from acme.om.trust.impl.manager import TrustOptions
from acme.om.trust.impl.placement import PlacementCloudImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.impl.manager import WorkOptions
from acme.om.workspaces.impl.manager import WorkspacesOptions
from acme.workers.maintenance.sessions import StalledOptions, StalledSessionsSweep
from acme.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)

MEDIA_PURGE_BATCH = 100
"""Files one media purge erases. Each is an object deleted from the store, one
request apiece, before its row, so the batch is smaller than the rows'."""

AGENT_SESSION_PURGE_BATCH = 100
"""Sessions one purge across tenants takes up. Each costs a claim, a batch of
its history, and its row, three statements apiece, so the batch is smaller
than the rows'."""

RETENTION_SWEEP_BATCH = 100
"""Sessions one retention sweep takes up. A session past its content's life
costs a call to its tenant's key service, the engine's revocation, and an
audit entry, so the batch is smaller than the rows'."""

HOLD_SWEEP_BATCH = 100
"""Holds one read of the hold sweep takes. Each costs a read of its tenant
and a settlement through the gate, under its lines' locks."""

STALLED_SWEEP_BATCH = 100
"""Pending sessions one read of the stalled sweep takes. Each costs a read of
its tenant and an enqueue."""


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
) -> Managers:
    """The managers, each one the sweep purges through with its retention and
    its batch from the settings. The worker is the one process that purges,
    so it is the one that sets them."""
    batch = settings.worker_purge_batch
    return build_managers(
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
        retention_options=RetentionOptions(sweep_batch=RETENTION_SWEEP_BATCH, purge_batch=batch),
        placement_options=PlacementOptions(purge_batch=batch),
        hosts_options=HostsOptions(purge_batch=batch),
        platform_agents_options=PlatformAgentsOptions(purge_batch=batch),
        projects_options=ProjectsOptions(purge_batch=batch),
        workspaces_options=WorkspacesOptions(purge_batch=batch),
    )


class WorkerContainer:
    def __init__(
        self,
        settings: MaintenanceSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
        integrations: IntegrationsInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.integrations = integrations
        # The trust swimlane, for its purge: the sweep runs no tool call, so
        # its placement and its probe are the defaults that act on nothing.
        executor = Executor(
            kind=ExecutorKind.CLOUD, credential_id=new_id(), label=settings.worker_id
        )
        self.trust = TrustLayer(
            storage,
            infra,
            placement=PlacementCloudImpl(executor),
            probe=KeyProbeAbsentImpl(),
            options=TrustOptions(purge_batch=settings.worker_purge_batch),
        ).build(managers)
        # Where the world's events come in, and the work they set going; with
        # playbooks and knowledge, for their purges.
        batch = settings.worker_purge_batch
        self.intake = build_intake(storage, managers, options=IntakeOptions(purge_batch=batch))
        self.automations = build_automations(
            storage, managers, options=AutomationsOptions(purge_batch=batch)
        )
        self.playbooks = PlaybooksLayer(storage, options=PlaybooksOptions(purge_batch=batch)).build(
            managers
        )
        self.knowledge = build_knowledge(
            storage, managers, options=KnowledgeOptions(purge_batch=batch)
        )
        # The platform's duties the sweep carries across tenants: a hold
        # nobody settled settles through the gate whose ledger holds it, at
        # the provider's bill, else whole; and a session pending with no
        # loop has its run asked for again.
        self.holds = HoldSweepImpl(
            storage.get_ledger_storage(),
            managers.budget_gate,
            managers.tenancy,
            ProviderBillsUnknownImpl(),
            HoldSweepOptions(batch=HOLD_SWEEP_BATCH),
        )
        self.stalled = StalledSessionsSweep(
            managers.agent_sessions,
            managers.steps,
            managers.work,
            managers.tenancy,
            StalledOptions(batch=STALLED_SWEEP_BATCH),
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
        return cls(
            settings,
            storage,
            infra,
            worker_managers(storage, infra, integrations, settings),
            integrations,
        )

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: MaintenanceSettings | None = None,
        integrations: IntegrationsInterface | None = None,
    ) -> WorkerContainer:
        settings = settings or MaintenanceSettings.model_validate(
            {"_env_file": None, "environment": "test", "worker_id": "maintenance-test"}
        )
        integrations = integrations or IntegrationsOverImpl(
            IdentityProviderTwinImpl(), absent_model_providers()
        )
        return cls(
            settings,
            storage,
            infra,
            worker_managers(storage, infra, integrations, settings),
            integrations,
        )

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
