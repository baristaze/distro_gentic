"""The platform's half of the maintenance worker: what it sets on the
platform's managers it purges through, the layers it builds over them, and
what its sweep runs beside the engine's. That is the platform's purges of a
tenant and the product's (`acme.om.product_namespaces`), each before the
purge it names; its duties across tenants; its ticks; its work handlers;
and its delivery providers. The container builds one `WorkerPlatform`, and
`main.build_loop` hands the engine's own steps to it."""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from acme.infra.impl.settings import InfraSettings
from acme.infra.root import InfraInterface
from acme.integrations.mcp.sdk import McpClientSdkImpl
from acme.integrations.root import IntegrationsInterface
from acme.om import product_namespaces
from acme.om.agent_automations.impl.manager import AgentAutomationsOptions
from acme.om.agent_automations.root import build_agent_automations
from acme.om.agent_billing.impl.sweep import HoldSweepImpl, HoldSweepOptions
from acme.om.agent_billing.root import build_agent_billing_purge
from acme.om.agent_billing.sweep import ProviderBillsUnknownImpl
from acme.om.agent_knowledge.impl.manager import AgentKnowledgeOptions
from acme.om.agent_knowledge.root import build_agent_knowledge
from acme.om.agent_playbooks.impl.manager import AgentPlaybooksOptions
from acme.om.agent_playbooks.root import AgentPlaybooksLayer
from acme.om.agent_projects.impl.manager import AgentProjectsOptions
from acme.om.agent_workspaces.impl.executor import ExecutorOptions
from acme.om.agent_workspaces.impl.manager import AgentWorkspacesOptions
from acme.om.base import new_id
from acme.om.cloud_pool.impl.manager import CloudPoolOptions
from acme.om.connectors.impl.manager import ConnectorsOptions
from acme.om.connectors.root import build_connectors
from acme.om.context import AppContext, AppType, RequestContext
from acme.om.exec_relay.impl.manager import ExecRelayOptions
from acme.om.hosts.impl.manager import HostsOptions
from acme.om.intake.impl.manager import IntakeOptions
from acme.om.intake.root import build_intake
from acme.om.park_alerts.impl.manager import ParkAlertsOptions
from acme.om.park_alerts.root import build_park_alerts
from acme.om.placement.impl.manager import PlacementOptions
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.impl.manager import PlatformAgentsOptions
from acme.om.platform_root import PlatformManagers, PlatformPorts, PlatformRootOptions, ProductKinds
from acme.om.retention.impl.manager import RetentionOptions
from acme.om.root import LOCAL
from acme.om.storage.root import StorageInterface
from acme.om.trust.impl.keys import KeyProbeAbsentImpl
from acme.om.trust.impl.manager import TrustOptions
from acme.om.trust.impl.placement import PlacementCloudImpl
from acme.om.trust.root import TrustLayer
from acme.om.trust.types.identities import Executor, ExecutorKind
from acme.om.work.types.handler import WorkHandlerInterface
from acme.om.work.types.work_item import WorkKind
from acme.workers.maintenance.deliveries import DeliveryProviderInterface
from acme.workers.maintenance.feedback import FeedbackDeliveriesImpl
from acme.workers.maintenance.loop import (
    AcrossStep,
    AgentFleetStep,
    PurgeStep,
    TickStep,
    WorkerLoop,
)
from acme.workers.maintenance.members import MemberLeftHandlerImpl
from acme.workers.maintenance.sessions import StalledOptions, StalledSessionsSweep
from acme.workers.maintenance.settings import MaintenanceSettings
from acme.workers.maintenance.validations import ValidationHandlerImpl

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

SHARE_CARRY_BATCH = 100
"""Shares one carry takes up. Each costs a read of its tenant's cap, a write
of it where there is none, and the share's mark."""


def cloud_pool_options(settings: InfraSettings) -> CloudPoolOptions:
    """The cloud pool as the settings name it, on the machines infra chose:
    the runner starts its machines, and the sweep lets them go."""
    return CloudPoolOptions(
        prefix=settings.machine_prefix,
        image=settings.cloud_pool_image,
        machine_image=settings.machine_image,
        warm=settings.cloud_pool_warm,
        api_url=settings.cloud_pool_api_url,
        boot=timedelta(seconds=settings.machine_boot_timeout_seconds),
    )


def worker_platform_options(
    settings: MaintenanceSettings,
    storage: StorageInterface,
    ports: PlatformPorts,
    platform_agents: PlatformAgents | None,
) -> PlatformRootOptions:
    """What the worker sets on the platform's managers: each one's batch, the
    retention sweep's, the cloud pool's machines with the request stage a
    purge of them runs under, minted here at the worker's edge, and the
    product's ports."""
    batch = settings.worker_purge_batch
    app = AppContext(type=AppType.WORKER, version=f"{settings.service_name}@{settings.version}")

    def stage() -> RequestContext:
        return RequestContext(request_id=new_id(), app=app)

    return PlatformRootOptions(
        platform_agents=platform_agents,
        retention_options=RetentionOptions(sweep_batch=RETENTION_SWEEP_BATCH, purge_batch=batch),
        placement_options=PlacementOptions(purge_batch=batch),
        hosts_options=HostsOptions(purge_batch=batch),
        platform_agents_options=PlatformAgentsOptions(purge_batch=batch),
        agent_projects_options=AgentProjectsOptions(purge_batch=batch),
        relay_options=ExecRelayOptions(purge_batch=batch),
        agent_workspaces_options=AgentWorkspacesOptions(purge_batch=batch),
        cloud_pool_options=cloud_pool_options(settings),
        cloud_pool_stage=stage,
        executor=ports.executor,
        executor_options=ExecutorOptions(image=settings.workspace_image),
        work_product=ports.work_product,
        agent_session_projects=ports.agent_session_projects,
        workspace_agent_projects=ports.workspace_agent_projects,
        product_kinds=ports.kinds,
        # An agent automation's start and an intake event make sessions here,
        # each with its kind manual.
        agents_layer=AgentPlaybooksLayer(storage).agents,
    )


def ordered[S](
    steps: Mapping[str, S], inserted: Iterable[tuple[str, S, str | None]]
) -> dict[str, S]:
    """`steps` in their order, with each of `inserted` before the step it
    names, or after every other when it names none. A name already held, or
    an anchor that names no step, is refused at boot."""
    names = list(steps)
    found = dict(steps)
    for name, step, before in inserted:
        if name in found:
            raise ValueError(f"purge {name} is registered twice")
        if before is None:
            names.append(name)
        elif before in found:
            names.insert(names.index(before), name)
        else:
            raise ValueError(f"purge {name} runs before {before}, which is no purge")
        found[name] = step
    return {name: found[name] for name in names}


class WorkerPlatform:
    """The layers the worker builds over the platform's managers, for their
    purges and their duties, and the product's namespaces, for theirs."""

    def __init__(
        self,
        settings: MaintenanceSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: PlatformManagers,
        integrations: IntegrationsInterface,
        kinds: ProductKinds,
    ) -> None:
        """`kinds` are the product's, whose agent automation actions its
        firings and its ticks run."""
        self._managers = managers
        batch = settings.worker_purge_batch
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
            options=TrustOptions(purge_batch=batch),
        ).build(managers)
        # Where the world's events come in, and the work they set going; with
        # agent playbooks, agent knowledge, and park alerts, for their purges.
        self.intake = build_intake(storage, managers, options=IntakeOptions(purge_batch=batch))
        # Outside a local stack, an agent automation's session starts in an
        # agent project: a start that names none fires nothing.
        self.agent_automations = build_agent_automations(
            storage,
            managers,
            agent_project_required=settings.environment != LOCAL,
            options=AgentAutomationsOptions(purge_batch=batch),
            actions=kinds.actions,
            agent_playbooks=lambda: self.agent_playbooks,
        )
        self.agent_playbooks = AgentPlaybooksLayer(
            storage, options=AgentPlaybooksOptions(purge_batch=batch)
        ).build(managers)
        self.agent_knowledge = build_agent_knowledge(
            storage, managers, options=AgentKnowledgeOptions(purge_batch=batch)
        )
        self.connectors = build_connectors(
            storage,
            infra,
            managers,
            client=McpClientSdkImpl(),
            options=ConnectorsOptions(purge_batch=batch),
        )
        # Agent billing's account, for its purge; its ledger stays.
        self.agent_billing = build_agent_billing_purge(storage, managers)
        # The platform's duties the sweep carries across tenants: a hold
        # nobody settled settles through the money gate whose ledger holds
        # it, at the provider's bill, else whole; and a session pending with
        # no loop has its run asked for again.
        self.holds = HoldSweepImpl(
            storage.get_spend_ledger_storage(),
            managers.budget_gate,
            managers.tenancy,
            ProviderBillsUnknownImpl(),
            HoldSweepOptions(batch=HOLD_SWEEP_BATCH),
        )
        self.stalled = StalledSessionsSweep(
            managers.agent_sessions,
            managers.work,
            managers.tenancy,
            StalledOptions(batch=STALLED_SWEEP_BATCH),
        )
        self.park_alerts = build_park_alerts(
            storage,
            managers,
            integrations,
            self.intake,
            options=ParkAlertsOptions(purge_batch=batch),
        )
        # The product's namespaces, each built once here for its purges.
        self.products = product_namespaces.PRODUCT_NAMESPACES.swept(storage, managers)

    @property
    def ticks(self) -> dict[str, TickStep]:
        """Per tenant, once a pass, what its time sets going: each schedule of
        its agent automations fires once for the slot it is in, whichever
        worker's sweep comes first."""
        return {"agent_automations": self.agent_automations.tick}

    def purges(self, engine: Mapping[str, PurgeStep]) -> dict[str, PurgeStep]:
        """The engine's purges of a tenant, with the platform's and the
        product's each before the purge it names. A deleted tenant's matrix
        pins and choices of fill go with the models' purge, through the
        matrix's face over the models manager."""
        managers = self._managers
        platform: list[tuple[str, PurgeStep, str | None]] = [
            # Its validation policies, then its runs, validations, and
            # hypotheses and findings under the purge login.
            ("evidence", managers.evidence.purge_tenant, "artifacts"),
            ("placement", managers.placement.purge_tenant, "artifacts"),
            ("hosts", managers.hosts.purge_tenant, "artifacts"),
            ("validation_sessions", managers.platform_agents.purge_tenant, "artifacts"),
            # Its exec items with their output, its controls, its bindings.
            ("exec_relay", managers.exec_relay.purge_tenant, "artifacts"),
            ("agent_workspaces", managers.agent_workspaces.purge_tenant, "artifacts"),
            # Each session's agent project row, then the tenant's agent
            # projects; each session's retention snapshot, then the tenant's
            # policy, once its sessions' key versions are gone.
            ("agent_projects", managers.agent_projects.purge_tenant, "budgets"),
            ("retention", managers.retention.purge_tenant, "budgets"),
            ("agent_billing", self.agent_billing.purge_tenant, None),
            # Its secrets' names, its keys' records with their values in the
            # store, and its operators' content grants.
            ("trust", self.trust.trust.purge_tenant, None),
            # Its identity links and work bindings, its agent automations and
            # their runs, its agent playbooks and their invocations, its agent
            # knowledge, and who was told what waited on them.
            ("intake", self.intake.purge_tenant, None),
            ("agent_automations", self.agent_automations.purge_tenant, None),
            ("agent_playbooks", self.agent_playbooks.purge_tenant, None),
            ("agent_knowledge", self.agent_knowledge.purge_tenant, None),
            # Its connectors, each credential with them, and what sessions pinned.
            ("connectors", self.connectors.purge_tenant, None),
            ("park_alerts", self.park_alerts.purge_tenant, None),
        ]
        products = [purge for swept in self.products for purge in swept.purges]
        return ordered(ordered(engine, platform), products)

    def across(self, engine: Mapping[str, AcrossStep]) -> dict[str, AcrossStep]:
        """The engine's duties across tenants, then the platform's, then the
        product's."""
        managers = self._managers

        async def carry_caps(rctx: RequestContext) -> int:
            return await managers.placement_operator.carry_caps(SHARE_CARRY_BATCH)

        platform: list[tuple[str, AcrossStep, str | None]] = [
            # Each session past its content's life: its key destroyed by the
            # tenant's key service, revoked, and audited; past its shape's,
            # marked for the purge of its tenant. A tightened policy reaches
            # each session first.
            ("retention", managers.retention.sweep, None),
            # Each hold no settlement closed an hour after it opened: at the
            # provider's bill, else whole, released only on its proof.
            ("holds", self.holds.settle_open, None),
            # Each session pending with no write since a run's time: its run
            # is asked for again, once a write.
            ("stalled_sessions", self.stalled, None),
            # Each exec item whose host's lease ran out: an unsafe one ends
            # `interrupted`, a repeatable one waits for its host again.
            ("exec_relay", managers.exec_relay.settle_expired, None),
            # Each share the release before wrote: the number of its loops at
            # once, carried as the tenant's own cap on its loop lane, once.
            ("share_caps", carry_caps, None),
        ]
        products = [(name, step, None) for swept in self.products for name, step, _ in swept.sweeps]
        return ordered(ordered(engine, platform), products)

    def across_batches(self, engine: Mapping[str, int]) -> dict[str, int]:
        """The batches of the duties whose batch is not the loop's: the
        engine's, the platform's, and each of the product's that names one."""
        own = {
            "retention": RETENTION_SWEEP_BATCH,
            "holds": HOLD_SWEEP_BATCH,
            "stalled_sessions": STALLED_SWEEP_BATCH,
            "share_caps": SHARE_CARRY_BATCH,
        }
        products = {
            name: batch
            for swept in self.products
            for name, _, batch in swept.sweeps
            if batch is not None
        }
        return {**engine, **own, **products}

    @property
    def agent_fleet(self) -> AgentFleetStep:
        """The platform's signals across every tenant, by bounded labels: the
        gauges the operator dashboard draws, set once a pass."""
        return self._managers.placement_operator.agent_fleet_counts

    def handlers(
        self, engine: Mapping[str, WorkHandlerInterface]
    ) -> dict[str, WorkHandlerInterface]:
        """The engine's work handlers, with the platform's beside them: a
        member who left a team org, and a validation."""
        return {
            **engine,
            WorkKind.MEMBER_LEFT: MemberLeftHandlerImpl(self.intake),
            WorkKind.VALIDATION: ValidationHandlerImpl(self._managers.platform_agents),
        }

    def providers(
        self, engine: Mapping[str, DeliveryProviderInterface[Any]]
    ) -> dict[str, DeliveryProviderInterface[Any]]:
        """The engine's delivery providers, with the world's events beside
        them."""
        return {**engine, "feedback": FeedbackDeliveriesImpl(self.intake, self.agent_automations)}


class PlatformWorkerLoop(WorkerLoop):
    """The worker's loop with the platform's steps beside the engine's: the
    loop takes the engine's purges, duties, batches, and handlers as
    `main.build_loop` names them, and runs each of the platform's and the
    product's with them, with the platform's ticks and its fleet gauges."""

    def __init__(
        self,
        platform: WorkerPlatform,
        *,
        purges: Mapping[str, PurgeStep],
        handlers: Mapping[str, WorkHandlerInterface],
        across: Mapping[str, AcrossStep] | None = None,
        across_batches: Mapping[str, int] | None = None,
        **loop: Any,
    ) -> None:
        super().__init__(
            purges=platform.purges(purges),
            handlers=platform.handlers(handlers),
            across=platform.across(across or {}),
            across_batches=platform.across_batches(across_batches or {}),
            ticks=platform.ticks,
            agent_fleet=platform.agent_fleet,
            **loop,
        )
