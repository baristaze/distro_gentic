"""The platform's root: every manager the platform adds, built over the
engine's graph through the root's hooks (`acme.om.root_hooks`), and handed
back as one frozen object, `PlatformManagers`: the engine's `Managers` with
the platform's beside them. What a process sets on the platform's managers
is one options object, `PlatformRootOptions`; what a product adds to the
platform's kinds is `ProductKinds`, declared once in
`acme.om.product_kinds`. Every process builds its managers with
`build_platform_managers`."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypedDict, Unpack
from uuid import UUID

from acme.infra.cache import CacheScope
from acme.infra.keys import KeyServiceInterface
from acme.infra.root import InfraInterface
from acme.infra.transports import TransportInterface
from acme.integrations.events import IntegrationAbsentImpl
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_automations import AgentAutomationsManagerInterface
from acme.om.agent_automations.actions import AgentAutomationActionInterface
from acme.om.agent_billing.gate import MoneyGateInterface
from acme.om.agent_billing.impl.gate import MoneyCallGateImpl
from acme.om.agent_billing.impl.prices import PriceBookTableImpl
from acme.om.agent_knowledge import AgentKnowledgeManagerInterface
from acme.om.agent_projects import AgentProjectsManagerInterface
from acme.om.agent_projects.impl.manager import AgentProjectsManagerImpl, AgentProjectsOptions
from acme.om.agent_projects.impl.policies import SessionAgentProjectsBoundImpl
from acme.om.agent_projects.impl.retention import SessionAgentProjectBoundImpl
from acme.om.agent_projects.impl.sessions import AgentSessionsInAgentProjectImpl
from acme.om.agent_projects.policies import SessionAgentProjectsInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.impl.manager import AgentSessionsOptions
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agent_steps.impl.manager import AgentStepsOptions
from acme.om.agent_workspaces import AgentWorkspacesManagerInterface
from acme.om.agent_workspaces import rules as workspace_rules
from acme.om.agent_workspaces.agent_projects import (
    PullRequestsInterface,
    SourceControlInterface,
    WorkspaceAgentProjectsInterface,
)
from acme.om.agent_workspaces.git import RepositoryReaderInterface, WorkspaceGitInterface
from acme.om.agent_workspaces.impl.agent_projects import (
    PullRequestsNullImpl,
    WorkspaceAgentProjectsBoundImpl,
)
from acme.om.agent_workspaces.impl.executor import ExecutorAgentWorkspacesImpl, ExecutorOptions, Pin
from acme.om.agent_workspaces.impl.forge import SourceControlAbsentImpl, SourceControlForgeImpl
from acme.om.agent_workspaces.impl.git import GitOptions, WorkspaceGitTransportImpl
from acme.om.agent_workspaces.impl.manager import AgentWorkspacesManagerImpl, AgentWorkspacesOptions
from acme.om.agent_workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.agent_workspaces.impl.sessions import AgentSessionsPinnedImpl
from acme.om.agent_workspaces.impl.tools import HeldWorkspaces, ToolsManagerAgentWorkspacesImpl
from acme.om.agent_workspaces.impl.work_product import WorkProductAgentWorkspacesImpl
from acme.om.agent_workspaces.types.host import HostOffer
from acme.om.agents import AgentsManagerInterface, ResultGateInterface
from acme.om.agents.attached import AttachedToolsetsInterface, AttachedToolsetsNoneImpl
from acme.om.agents.impl.loop import LoopOptions
from acme.om.agents.impl.manager import AgentsOptions
from acme.om.agents.sink import StreamSinkInterface
from acme.om.agents.types.kind import AgentKind, AgentKindCatalog
from acme.om.attribution import PrincipalContext
from acme.om.attribution.impl.manager import AttributionOptions
from acme.om.base import utcnow
from acme.om.benchmarks import BenchmarksManagerInterface
from acme.om.benchmarks.impl.manager import BenchmarksManagerImpl
from acme.om.change_events import ChangeEventsManagerInterface
from acme.om.change_events.impl.manager import ChangeEventsOptions
from acme.om.cloud_pool import CloudPoolManagerInterface
from acme.om.cloud_pool.impl.manager import CloudPoolManagerImpl, CloudPoolOptions
from acme.om.context import RequestContext, TenantContext
from acme.om.evidence import (
    EvidenceManagerInterface,
    ExecutorInterface,
    Executors,
    WorkProductInterface,
)
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.manager import EvidenceManagerImpl, EvidenceOptions
from acme.om.evidence.impl.ports import ExecutorAbsentImpl
from acme.om.evidence.rules import PROTECTED_CEILING
from acme.om.exceptions import NotFound, Unavailable
from acme.om.exec_relay import ExecRelayManagerInterface
from acme.om.exec_relay.impl.instances import PlacedInstancesRelayedImpl
from acme.om.exec_relay.impl.manager import ExecRelayManagerImpl, ExecRelayOptions
from acme.om.exec_relay.impl.placement import PlacementClaimsRelayedImpl
from acme.om.exec_relay.impl.transport import TransportRelayImpl
from acme.om.exec_relay.impl.workspaces import PlacedWorkspacesRelayedImpl
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.impl.manager import HostsManagerImpl, HostsOptions
from acme.om.hosts.impl.placement import inside_wall
from acme.om.hosts.rules import ENROLLMENT_PREFIX
from acme.om.idempotency.impl.manager import IdempotencyOptions
from acme.om.intake import IntakeManagerInterface
from acme.om.language_models.impl.manager import LanguageModelsOptions
from acme.om.language_models.layer import LanguageModelsLayer
from acme.om.language_models.prices import ModelPricesInterface
from acme.om.leases.hooks import LeasableResourceKindInterface
from acme.om.leases.impl.manager import LeasesOptions
from acme.om.leases.kinds import ResourceKinds, ResourceKindSpec
from acme.om.leases.types.request import ASK_PAYLOADS
from acme.om.media.impl.manager import MediaOptions
from acme.om.orchestrations.impl.manager import OrchestrationsOptions
from acme.om.outbox import OutboxRelayInterface
from acme.om.park_alerts.impl.manager import ParkAlertsOptions
from acme.om.placement import PlacementManagerInterface, PlacementOperatorManagerInterface
from acme.om.placement.impl.manager import PlacementManagerImpl, PlacementOptions
from acme.om.placement.impl.operator import (
    PlacementOperatorManagerImpl,
    PlacementOperatorOptions,
)
from acme.om.placement.kinds import (
    ClaimantKinds,
    ClaimantKindSpec,
    platform_claimant_kinds,
    platform_work_kinds,
)
from acme.om.platform_agents import PlatformAgentsManagerInterface
from acme.om.platform_agents.catalog import (
    PlatformAgents,
    refuse_reach,
    with_assistant_tools,
    with_shipped,
)
from acme.om.platform_agents.impl.gate import ResultGateReviewImpl
from acme.om.platform_agents.impl.manager import PlatformAgentsManagerImpl, PlatformAgentsOptions
from acme.om.platform_agents.kinds import (
    GRACES,
    PROMPT_CACHE_LIFE,
    SHIPPED,
    TOOLSETS,
    WARM_GRACE,
    WORKSPACE_BASE_KINDS,
)
from acme.om.privacy import PrivacyManagerInterface
from acme.om.privacy.impl.keys import AgentSessionKeysImpl
from acme.om.privacy.impl.records import RecordSealKeysImpl
from acme.om.retention import RetentionManagerInterface
from acme.om.retention.agent_projects import SessionAgentProjectInterface
from acme.om.retention.impl.keys import (
    KeyServiceByTenantImpl,
    KeyServiceLocalImpl,
    TenantKeysImpl,
)
from acme.om.retention.impl.manager import RetentionManagerImpl, RetentionOptions
from acme.om.retention.impl.sessions import AgentSessionsRetainedImpl
from acme.om.retention.keys import TenantKeysInterface
from acme.om.root import LOCAL, Managers, build_managers, refuse_quiet_spend
from acme.om.root_hooks import RootHooksInterface, SessionPurge
from acme.om.spend_budgets import SpendBudgetGateInterface, SpendBudgetsManagerInterface
from acme.om.spend_budgets.impl.manager import SpendBudgetsOptions
from acme.om.spend_budgets.pricing import PricingInterface
from acme.om.storage.root import StorageInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.impl.manager import TenancyOptions
from acme.om.tenancy.impl.operator import TenancyOperatorOptions
from acme.om.tenancy.rules import CREDENTIAL_PREFIXES
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.attachments import AttachmentReaderInterface
from acme.om.tools.impl.bases import AgentWorkspaceBases
from acme.om.tools.impl.manager import ForkPoints, ToolsOptions
from acme.om.tools.impl.snapshots import SnapshotStore
from acme.om.tools.seal import RecordSealInterface, SnapshotSealInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, ToolPolicyLayer, ToolPolicyRule
from acme.om.tools.types.tool import ToolClass
from acme.om.tools.types.toolset import Toolset
from acme.om.trust.owners import SecretOwnerInterface
from acme.om.watch.kinds import StreamKind
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.hashes import PromptHashInterface
from acme.om.windows.impl.gate import CallGateSpendBudgetImpl
from acme.om.windows.seal import ToolOutputSealInterface
from acme.om.windows.types.policy import CompactionPolicy
from acme.om.work.impl.manager import Lanes, WorkOptions
from acme.om.work.kinds import WorkKinds, WorkKindSpec


@dataclass(frozen=True)
class PlatformManagers(Managers):
    """The engine's managers, and the platform's beside them."""

    retention: RetentionManagerInterface
    evidence: EvidenceManagerInterface
    placement: PlacementManagerInterface
    placement_operator: PlacementOperatorManagerInterface
    agent_workspaces: AgentWorkspacesManagerInterface
    hosts: HostsManagerInterface
    exec_relay: ExecRelayManagerInterface
    cloud_pool: CloudPoolManagerInterface
    platform_agents: PlatformAgentsManagerInterface
    agent_projects: AgentProjectsManagerInterface
    benchmarks: BenchmarksManagerInterface
    kinds: AgentKindCatalog
    """The kinds every session starts on, each version they run: what a
    text a person writes for them, such as an agent playbook, reaches."""


ProductTools = Callable[[Callable[[], PlatformManagers]], tuple[ToolInterface, ...]]
"""A product's tools, built over the managers as the root answers them once
it has built them: a tool keeps the callable and reads a manager through it
when it is called, as the platform's own tools do."""


def no_tools(managers: Callable[[], PlatformManagers]) -> tuple[ToolInterface, ...]:
    """A product with no tools of its own."""
    return ()


ProductActions = Callable[
    [Callable[[], PlatformManagers]], tuple[AgentAutomationActionInterface, ...]
]
"""A product's own kinds of agent automation action, built over the managers as
the root answers them, as a product's tools are."""


def no_actions(
    managers: Callable[[], PlatformManagers],
) -> tuple[AgentAutomationActionInterface, ...]:
    """A product with no agent automation action of its own."""
    return ()


ProductResources = Callable[[Callable[[], PlatformManagers]], tuple[ResourceKindSpec, ...]]
"""A product's own resource kinds, each with the shape of its ask, its
hooks, and its check of an ask if it has one, built over the managers as
the root answers them, as a product's tools are."""


def no_resources(managers: Callable[[], PlatformManagers]) -> tuple[ResourceKindSpec, ...]:
    """A product with no resource kind of its own."""
    return ()


@dataclass(frozen=True)
class ProductKinds:
    """What a product adds to the platform's kinds: its agent kinds, every
    version it still runs; its tools, and the authorization classes they
    declare beside the platform's, with the ceiling any of those classes
    holds whatever a tenant's layer says; its work kinds, each with its payload,
    its permission, its lane, and the claimant kind that takes it through
    the gateway; its claimant kinds; its secret owner kinds (`TrustLayer`);
    its stream kinds, each with its bounds (`watch.root.build_stream`) and the
    claimant kinds of its own that write and read it, if any; its executors, each by
    the name a check's `executor` gives; and its kinds of agent automation
    action, each acting in a firing, saying when the run it started
    ended, and checking the person who writes one (`agent_automations.actions`);
    and its resource kinds, each with the shape of its ask, the hooks a
    grant asks, and its check of an ask if it has one (`leases.kinds`).
    Its toolsets join the platform's (`platform_agents.kinds.TOOLSETS`),
    and each toolset its kinds name is one of the two; a name the
    platform's toolsets hold is refused. Each of its agent kinds may name
    its warm grace, how long its workspace stays held after a loop, at
    most the prompt cache's life; one it names none for takes the
    default (`warm_grace`). It names, by name and version, the agent kinds
    of its own whose workspace starts from the workspace base its session's
    agent project names (`workspace_bases`), as the platform names its software engineer
    (`platform_agents.kinds.WORKSPACE_BASE_KINDS`); a pair that is no agent
    kind of its own is refused.
    Its agent kinds join the platform's catalog, which refuses a version
    declared twice, and its tools the
    platform's, where a registry refuses two of one name. Every other kind
    registers beside the platform's own, which go through the same registries,
    and a name the platform holds is refused, so a product adds kinds and
    never changes one of the platform's. A product's ceiling names a class
    of its own, and the platform holds none for it, so it never loosens or
    doubles one of the platform's (`product_ceilings`). A product's work
    kind names its claimant kind, since no worker of the platform's runs
    it."""

    agents: tuple[AgentKind, ...] = ()
    tools: ProductTools = no_tools
    classes: tuple[str, ...] = ()
    ceilings: Mapping[str, Decision] = field(default_factory=lambda: {})
    work: tuple[WorkKindSpec, ...] = ()
    claimants: tuple[ClaimantKindSpec, ...] = ()
    secret_owners: tuple[SecretOwnerInterface, ...] = ()
    streams: tuple[StreamKind, ...] = ()
    executors: Mapping[str, ExecutorInterface] = field(default_factory=lambda: {})
    actions: ProductActions = no_actions
    assistant_tools: tuple[str, ...] = ()
    resources: ProductResources = no_resources
    toolsets: tuple[Toolset, ...] = ()
    graces: Mapping[str, timedelta] = field(default_factory=lambda: {})
    workspace_bases: frozenset[tuple[str, int]] = frozenset()

    def __post_init__(self) -> None:
        platform = {toolset.name for toolset in TOOLSETS}
        declared = {(toolset.name, toolset.version): toolset for toolset in self.toolsets}
        if len(declared) != len(self.toolsets):
            raise ValueError("the product declares a version of a toolset twice")
        for toolset in self.toolsets:
            if toolset.name in platform:
                raise ValueError(
                    f"toolset {toolset.name} is the platform's, which no product changes"
                )
        declared.update({(toolset.name, toolset.version): toolset for toolset in TOOLSETS})
        own = {kind.name for kind in self.agents}
        for kind in self.agents:
            for toolset in (*kind.toolsets, *kind.deferred):
                if declared.get((toolset.name, toolset.version)) != toolset:
                    raise ValueError(
                        f"{kind.name} v{kind.version} names toolset {toolset.name} at version "
                        f"{toolset.version}, which neither the platform nor the product declares"
                    )
        for name, grace in self.graces.items():
            if name not in own:
                raise ValueError(
                    f"a warm grace names {name}, which is no agent kind of the product's"
                )
            if not timedelta(0) <= grace <= PROMPT_CACHE_LIFE:
                raise ValueError(
                    f"{name}'s warm grace of {grace} runs outside the prompt cache's life "
                    f"of {PROMPT_CACHE_LIFE}"
                )
        versions = {(kind.name, kind.version) for kind in self.agents}
        for name, version in sorted(self.workspace_bases):
            if (name, version) not in versions:
                raise ValueError(
                    f"the kinds that take their agent project's workspace base name {name} v{version}, "
                    "which is no agent kind of the product's"
                )
        for spec in self.work:
            if spec.claimant is None:
                raise ValueError(f"{spec.name} names no claimant kind, so nothing would claim it")
        # A stream a claimant writes or reads is bound to an item it holds,
        # and only a product's claimant holds one: the host's items are the
        # exec relay's.
        own = {claimant.name for claimant in self.claimants}
        for stream in self.streams:
            for role, kind in (("written", stream.claimant), ("read", stream.reader)):
                if kind is not None and kind not in own:
                    raise ValueError(
                        f"stream kind {stream.name} is {role} by {kind}, "
                        "which is no claimant kind of the product's"
                    )

    def warm_grace(self, kind: str) -> timedelta:
        """How long a session of `kind` keeps its workspace held after a
        loop, for a follow-up to find it warm: the grace the product names
        for one of its kinds, the platform's for one it ships, and the
        default for any other."""
        if kind in self.graces:
            return self.graces[kind]
        return GRACES.get(kind, WARM_GRACE)


TenantPurge = Callable[[TenantContext], Awaitable[int]]
"""A namespace's purge of a tenant deleted past its retention: a batch per
statement, answering how many rows went."""

SystemPurge = Callable[[RequestContext], Awaitable[int]]
"""A namespace's purge of its rows past their retention across tenants,
under the sweep's request stage, answering how many rows went."""


@dataclass(frozen=True)
class ProductPurge[M]:
    """A purge of a tenant a product's namespace runs, built over the
    namespace's managers: its name in the sweep, its step, and the purge it
    runs before (`before`), so its rows go before the rows they name. None
    runs it after every other."""

    name: str
    step: Callable[[M], TenantPurge]
    before: str | None = None


@dataclass(frozen=True)
class ProductSweep[M]:
    """A purge across tenants a product's namespace runs, built over the
    namespace's managers: its name in the sweep, its step, and the batch a
    whole one of says there may be more, None the sweep's own."""

    name: str
    step: Callable[[M], SystemPurge]
    batch: int | None = None


@dataclass(frozen=True)
class SweptNamespace:
    """A product's namespace as one process built it: its managers, and its
    purges bound to them, each with the purge it runs before."""

    name: str
    managers: object
    purges: tuple[tuple[str, TenantPurge, str | None], ...]
    sweeps: tuple[tuple[str, SystemPurge, int | None], ...]


@dataclass(frozen=True)
class ProductNamespace[M]:
    """A namespace a product adds: its name, how its managers are built over
    the storage and the platform's managers, once in each process that
    reads them, and the purges the maintenance worker runs of it."""

    name: str
    build: Callable[[StorageInterface, PlatformManagers], M]
    purges: tuple[ProductPurge[M], ...] = ()
    sweeps: tuple[ProductSweep[M], ...] = ()

    def swept(self, storage: StorageInterface, managers: PlatformManagers) -> SweptNamespace:
        """The namespace's managers, built once, and its purges over them."""
        own = self.build(storage, managers)
        return SweptNamespace(
            self.name,
            own,
            tuple((purge.name, purge.step(own), purge.before) for purge in self.purges),
            tuple((sweep.name, sweep.step(own), sweep.batch) for sweep in self.sweeps),
        )


@dataclass(frozen=True)
class ProductNamespaces:
    """What a product adds to the platform's namespaces, each once
    (`acme.om.product_namespaces`): the API serves each one's routes beside
    the platform's, and the maintenance worker runs its purges in order. A
    name declared twice is refused."""

    namespaces: tuple[ProductNamespace[Any], ...] = ()

    def __post_init__(self) -> None:
        names = [namespace.name for namespace in self.namespaces]
        if len(set(names)) != len(names):
            raise ValueError("the product declares a namespace twice")

    def swept(
        self, storage: StorageInterface, managers: PlatformManagers
    ) -> tuple[SweptNamespace, ...]:
        """Every namespace's managers, built once, with its purges."""
        return tuple(namespace.swept(storage, managers) for namespace in self.namespaces)


@dataclass(frozen=True)
class PlatformPorts:
    """The platform's ports a product hands each of its roots, each None for
    the platform's own: agent billing's money gate as the budget gate, the
    evidence's result gate over the work product, the platform's executor
    (the loud null in `local`), the workspaces' work product, and the
    agent projects' rows for a session's agent project, which its workspace binds and
    its retention narrows by. Outside `local`, a root refuses a quiet null
    for any of them. `kinds` is what the product adds to the platform's
    kinds, so every root reads the one registry: none adds nothing. Each
    process's entry point hands its root `PRODUCT_KINDS`
    (`acme.om.product_kinds`), where a product declares them once."""

    spend_budget_gate: SpendBudgetGateInterface | None = None
    result_gate: ResultGateInterface | None = None
    executor: ExecutorInterface | None = None
    work_product: WorkProductInterface | None = None
    agent_session_projects: SessionAgentProjectInterface | None = None
    workspace_agent_projects: WorkspaceAgentProjectsInterface | None = None
    kinds: ProductKinds = field(default_factory=ProductKinds)


PLATFORM_PREFIXES = (*CREDENTIAL_PREFIXES, ENROLLMENT_PREFIX, workspace_rules.PUSH_TOKEN_PREFIX)
"""The prefixes of the platform's credentials that are no claimant's: a
person's and an operator's, an enrollment token's, and a push token's. A
claimant kind's prefix is none of them, so a prefix names one kind."""


def refuse_quiet_nulls(environment: str, *capabilities: object) -> None:
    """Outside `local`, the platform's root refuses a quiet null result gate
    or platform port at boot, as the engine's refuses a quiet null budget
    gate or ledger: every success would end unverified, and a policy keyed
    by a session's agent project would never apply. A loud null is no such
    risk: it refuses each call itself."""
    refuse_quiet_spend(environment, *capabilities)


def product_ceilings(platform: ToolPolicyLayer, product: ProductKinds) -> ToolPolicyLayer:
    """The platform's ceilings with the product's beside them, one rule per
    class the product declares a ceiling for. A ceiling of a class the
    platform's engine knows, of a class the product does not declare, or of
    a class a platform ceiling already names is refused at boot, so a
    product caps its own classes and never touches the platform's."""
    platform_classes = {rule.authorization_class for rule in platform.rules}
    rules: list[ToolPolicyRule] = []
    for name, decision in product.ceilings.items():
        if name in {known.value for known in ToolClass}:
            raise ValueError(f"{name} is a platform class, and its ceiling is the platform's")
        if name not in product.classes:
            raise ValueError(f"a ceiling names {name}, which is no class of the product's")
        if name in platform_classes:
            raise ValueError(f"the platform already holds a ceiling for {name}")
        rules.append(ToolPolicyRule(authorization_class=name, decision=decision))
    return ToolPolicyLayer(rules=(*platform.rules, *rules))


def intake_absent() -> IntakeManagerInterface:
    """No intake in this process: a loud null, so a tool that binds its
    session's work refuses rather than act where no event can find it."""
    raise Unavailable("no intake binds a session's work in this process")


def agent_automations_absent() -> AgentAutomationsManagerInterface:
    """No agent automations in this process: a loud null, so a tool that reads
    the tenant's agent automations refuses rather than answer that it has none."""
    raise Unavailable("no agent automations are read in this process")


def agent_knowledge_absent() -> AgentKnowledgeManagerInterface:
    """No agent knowledge in this process: a loud null, so a tool that searches,
    reads, or suggests agent knowledge refuses rather than answer that none is
    kept."""
    raise Unavailable("no agent knowledge is kept in this process")


@dataclass(frozen=True)
class PlatformRootOptions:
    """What a process sets on the platform's managers. None keeps a manager's
    defaults, or wires the platform's own impl.

    `product_kinds` is what a product adds to the platform's kinds
    (`PlatformPorts.kinds`): its agent kinds, tools, classes, and their
    ceilings, which join the engine's `agent_kinds`, `tool_catalog`,
    `domain_classes`, and the tools' ceilings, each tool reading the
    managers built here at call time; its work kinds and claimant kinds,
    which the work queue and placement read beside the platform's; its
    executors, which run a check that names them; its kinds whose workspace
    starts from their agent project's workspace base, which the workspaces
    read beside the platform's (`WORKSPACE_BASE_KINDS`); and its resource
    kinds, which the leases manager reads beside `noop`. A name the
    platform holds is refused at boot. None adds nothing.

    `platform_agents` ships the platform's agents, with the corpus its
    assistant answers from: their kinds join `agent_kinds` and their tools
    join `tool_catalog`, ahead of the adopter's, and the product's
    `assistant_tools` join the assistant's. A catalog that holds two tools
    of one name, or lets the assistant reach past reading and handing work
    on, or a slot that names a tool the catalog does not hold, is refused
    at boot (`UnsafeConfiguration`). None ships none. `intake` answers the
    intake the process builds over these managers, where the software
    engineer's pull request is bound to its session; None binds nothing,
    so that tool opens none. `agent_knowledge` answers the agent knowledge
    the process builds over them, which the agents search, read, and
    suggest to; None keeps none, so those tools refuse. `agent_automations`
    answers the agent automations the process builds over them, which the
    assistant reads; None reads none, so those readers refuse.

    `tools_layer` wraps the tools manager before the loop and the root take
    it: a layer above the platform holds its own rules around every call,
    and sees each call the engine runs. `agents_layer` wraps the agents
    manager before anything that makes a session takes it: the agent
    projects, the platform's agents, the spawn tool, and the root's own.
    None takes each manager as it is. `attached_toolsets` answers the
    toolsets a session holds beyond its kind, a tenant's own: the loop
    folds them into the session's kind at each run. None attaches nothing.

    The evidence takes the platform's two ports: `executor`, the fresh
    executor validation runs on, and `work_product`, which reads what a
    session delivered, and which the result gate reads too. None wires the
    platform's executor, a fresh instance of the cloud's for each run, made
    and recorded as `executor_options` say, the image the process's
    workspaces run among them, or in `local` the loud null, which refuses
    every validation; and the workspaces' work product, the session's
    branch as its repository holds it, with the workspace this process
    holds for the session telling what was not delivered; one it does not
    hold, or one of no bound repository, is refused, so no success counts
    on a guess. The engine's `result_gate` None is the evidence's gate over
    the work product; outside `local`, a quiet null result gate or work
    product is refused at boot (`UnsafeConfiguration`). Whatever the
    engine's `tools_options` names, the tools take the platform's ceiling
    on a protected path beside its ceilings, and the product's on its own
    classes. The engine's `spend_budget_gate` as agent billing's money gate puts
    agent billing's call gate behind every model call, priced from the
    price book by version.

    `placement_options` is the plan tier of a tenant no operator gave one,
    and each tier's share, the cap its lane passes to the claim; None keeps
    the defaults. `hosts_options` is the lives of a host's credentials, the
    window a host counts as online, and its claim's lease; None keeps the
    defaults. `relay_options` is the lease a host renews on an `exec` item
    and the bounds of its output; None keeps the defaults.
    `transport_layer` wraps the transport infra chose before the tools and
    the checkout take it: the session runner puts the exec relay behind it
    for a session inside its tenant's wall, whose workspace is then the one
    a host of its pool prepared and holds. None takes infra's transport as
    it is, and makes every workspace on this machine. `cloud_pool_options`
    and `cloud_pool_stage` are the cloud pool's machines and the request
    stage its purge runs under.

    The platform's retention takes three. `tenant_keys` says whose key
    service holds each tenant's keys; None is infra's for every tenant, and
    in `local` the local key service over it, which destroys a session's
    key and reports it as a tenant's own service does. Elsewhere infra's
    holds the tenant's key alone, and the engine's revocation is the
    destruction. `agent_session_projects` names a new session's agent
    project; None reads the row the agent projects' start wrote, and a
    session with no row takes its tenant's policy unnarrowed (a quiet null
    one is refused outside `local`); and `retention_options` the sweep's
    batches.

    The platform's agent projects take `agent_projects_options`, the
    purges' batch. `session_policies` answers a session's agent project to
    the gate's budgets and to the evidence's policy; None reads the agent
    projects' rows, and a session with no row is charged to no agent
    project and judged by no policy.

    The workspaces take six. `workspace_host` is what this process, the
    host its tools run on, offers beyond its provider; None offers nothing
    more, as a host of the platform's cloud. `workspace_agent_projects`
    answers a session's agent project and the repository it binds (a quiet
    null one is refused outside `local`), and `pull_requests` why a
    session's branch is gone; None reads the agent projects' rows for the
    one, and knows no pull request, so a branch gone for any reason fails
    loudly. `source_control` opens a session's branch and pull request;
    None writes through the forge integration, and with no integrations,
    nowhere. `workspace_git` runs the checkout; None runs it in the
    workspace through the transport the tools take, so a workspace inside
    a tenant's wall is checked out there, from bundles the reader brings
    and source control pushes. `workspace_reader` reads what a session
    delivered from its repository; None fetches it into a fresh repository
    of this process's own, with the agent project's fetch credential, never
    from a network no workspace reaches, and from disk in `local` alone.
    `agent_workspaces_options` names those networks, and the sweep's
    batch. The other options are each manager's batch, as the process that
    sweeps sets them."""

    product_kinds: ProductKinds | None = None
    platform_agents: PlatformAgents | None = None
    platform_agents_options: PlatformAgentsOptions | None = None
    intake: Callable[[], IntakeManagerInterface] | None = None
    agent_knowledge: Callable[[], AgentKnowledgeManagerInterface] | None = None
    agent_automations: Callable[[], AgentAutomationsManagerInterface] | None = None
    tools_layer: Callable[[ToolsManagerInterface], ToolsManagerInterface] | None = None
    agents_layer: Callable[[AgentsManagerInterface], AgentsManagerInterface] | None = None
    attached_toolsets: AttachedToolsetsInterface | None = None
    executor: ExecutorInterface | None = None
    executor_options: ExecutorOptions | None = None
    work_product: WorkProductInterface | None = None
    evidence_options: EvidenceOptions | None = None
    placement_options: PlacementOptions | None = None
    hosts_options: HostsOptions | None = None
    relay_options: ExecRelayOptions | None = None
    transport_layer: Callable[[TransportInterface], TransportInterface] | None = None
    cloud_pool_options: CloudPoolOptions | None = None
    cloud_pool_stage: Callable[[], RequestContext] | None = None
    tenant_keys: TenantKeysInterface | None = None
    agent_session_projects: SessionAgentProjectInterface | None = None
    retention_options: RetentionOptions | None = None
    agent_projects_options: AgentProjectsOptions | None = None
    session_policies: SessionAgentProjectsInterface | None = None
    workspace_host: HostOffer | None = None
    workspace_agent_projects: WorkspaceAgentProjectsInterface | None = None
    pull_requests: PullRequestsInterface | None = None
    source_control: SourceControlInterface | None = None
    workspace_git: WorkspaceGitInterface | None = None
    workspace_reader: RepositoryReaderInterface | None = None
    agent_workspaces_options: AgentWorkspacesOptions | None = None


class EngineOptions(TypedDict, total=False):
    """The engine's root's keywords (`acme.om.root.build_managers`), which
    the platform's root hands on, its kinds, tools, classes, ceilings, and
    record seal joined to theirs."""

    media_options: MediaOptions | None
    idempotency_options: IdempotencyOptions | None
    change_events_options: ChangeEventsOptions | None
    work_options: WorkOptions | None
    orchestrations_options: OrchestrationsOptions | None
    leases_options: LeasesOptions | None
    steps_options: AgentStepsOptions | None
    agent_sessions_options: AgentSessionsOptions | None
    budgets_options: SpendBudgetsOptions | None
    language_models_options: LanguageModelsOptions | None
    model_prices: ModelPricesInterface | None
    language_models_layer: LanguageModelsLayer | None
    call_gate: CallGateInterface | None
    prompt_hash: PromptHashInterface | None
    tool_output_seal: ToolOutputSealInterface | None
    record_seal: RecordSealInterface | None
    snapshot_seal: SnapshotSealInterface | None
    compaction_policy: CompactionPolicy | None
    agents_options: AgentsOptions | None
    attribution_options: AttributionOptions | None
    agent_kinds: tuple[AgentKind, ...]
    principal_context: PrincipalContext | None
    result_gate: ResultGateInterface | None
    tools_options: ToolsOptions | None
    spend_budget_gate: SpendBudgetGateInterface | None
    stream_sink: StreamSinkInterface | None
    tool_catalog: tuple[ToolInterface, ...]
    attachment_reader: AttachmentReaderInterface | None
    domain_classes: tuple[str, ...]
    loop_options: LoopOptions | None
    environment: str


class RootHooksPlatformImpl(RootHooksInterface):
    """The platform's hooks into the engine's root for one build, and the
    managers it builds once the engine's are: hand it to `build_managers`
    as its hooks, with `engine_options()` as its keywords, then `build` the
    managers it answers. `build_platform_managers` does both."""

    def __init__(
        self,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface | None,
        options: PlatformRootOptions,
        engine: EngineOptions,
    ) -> None:
        self._storage = storage
        self._infra = infra
        self._integrations = integrations
        self._options = options
        self._engine = engine
        self._environment = engine.get("environment", LOCAL)
        self._built: PlatformManagers | None = None
        # The kinds every manager reads through: the platform's own, and the
        # product's beside them. A product's tools read the managers built
        # below, as the platform's own do, so each edge is bound at call time.
        product = options.product_kinds or ProductKinds()
        self._product = product
        agent_kinds = (*engine.get("agent_kinds", ()), *product.agents)
        tool_catalog = (*engine.get("tool_catalog", ()), *product.tools(lambda: self.managers))
        domain_classes = (*engine.get("domain_classes", ()), *product.classes)
        if options.platform_agents is not None:
            # Their tools read the managers built below, so each edge is bound
            # at call time.
            agent_kinds = (*with_assistant_tools(SHIPPED, product.assistant_tools), *agent_kinds)
            tool_catalog = with_shipped(
                options.platform_agents,
                tool_catalog,
                domain_classes,
                sessions=lambda: self.managers.agent_sessions,
                steps=lambda: self.managers.steps,
                agent_projects=lambda: self.managers.agent_projects,
                work=lambda: self.managers.work,
                hosts=lambda: self.managers.hosts,
                exec_relay=lambda: self.managers.exec_relay,
                agent_automations=options.agent_automations or agent_automations_absent,
                policies=lambda: self.managers.tools,
                agents=lambda: self.managers.agents,
                evidence=lambda: self.managers.evidence,
                agent_workspaces=lambda: self.managers.agent_workspaces,
                intake=options.intake or intake_absent,
                agent_knowledge=options.agent_knowledge or agent_knowledge_absent,
                integrations=IntegrationAbsentImpl
                if integrations is None
                else integrations.get_integration,
                budgets=lambda: self.managers.budgets,
            )
        self._agent_kinds = agent_kinds
        self._tool_catalog = tool_catalog
        self._domain_classes = domain_classes
        self._kinds = AgentKindCatalog(kinds=agent_kinds)
        self._work_kinds = platform_work_kinds().extended(product.work)
        self._claimant_kinds = ClaimantKinds(
            (*platform_claimant_kinds(), *product.claimants), reserved=PLATFORM_PREFIXES
        )
        # The ceilings: the options' own, the platform's on a protected path,
        # and the product's on its own classes.
        tool_options = engine.get("tools_options") or ToolsOptions()
        ceilings = tool_options.ceilings
        if PROTECTED_CEILING not in ceilings.rules:
            ceilings = ToolPolicyLayer(rules=(*ceilings.rules, PROTECTED_CEILING))
        ceilings = product_ceilings(ceilings, product)
        self._tool_options = tool_options.model_copy(update={"ceilings": ceilings})
        # Each tenant's keys in its own key service: the platform's, or the one
        # the tenant brought. In `local`, the platform's is the local key service
        # over infra's, which holds each session's key in this process.
        self._keys = options.tenant_keys or TenantKeysImpl(
            KeyServiceLocalImpl(infra.get_keys())
            if self._environment == LOCAL
            else infra.get_keys()
        )
        self._records = engine.get("record_seal") or RecordSealKeysImpl(
            AgentSessionKeysImpl(storage.get_privacy_storage(), KeyServiceByTenantImpl(self._keys)),
            storage.get_privacy_storage(),
        )
        # The transport infra chose, and the one the tools and the checkout
        # take: for a session inside its tenant's wall, the exec relay to its host.
        transport = infra.get_transport()
        self._placed = (
            transport if options.transport_layer is None else options.transport_layer(transport)
        )
        # A budget and a validation policy set per agent project are read through
        # the session's agent project.
        self._session_policies = options.session_policies or SessionAgentProjectsBoundImpl(
            storage.get_agent_project_storage()
        )
        self._book: PriceBookTableImpl | None = None

    @property
    def managers(self) -> PlatformManagers:
        """The managers `build` answered; a tool or an edge reads them at call
        time, after the build."""
        if self._built is None:
            raise RuntimeError("the platform's managers are read before they are built")
        return self._built

    def engine_options(self) -> EngineOptions:
        """The engine's keywords as the caller set them, with the platform's
        kinds, tools, classes, ceilings, and record seal joined to theirs."""
        engine = EngineOptions(**self._engine)
        engine["agent_kinds"] = self._agent_kinds
        engine["tool_catalog"] = self._tool_catalog
        engine["domain_classes"] = self._domain_classes
        engine["tools_options"] = self._tool_options
        engine["record_seal"] = self._records
        return engine

    @property
    def work_kinds(self) -> WorkKinds:
        return self._work_kinds

    @property
    def lanes(self) -> Lanes | None:
        # Every item goes to the lane where its environment is, which
        # placement answers. Placement claims through the work manager, so it
        # is built after it and the edge is bound at call time.
        return lambda org_id, item: self.managers.placement.lane_for(org_id, item)

    def resource_kinds(self, own: Mapping[str, LeasableResourceKindInterface]) -> ResourceKinds:
        # The mechanism's own, and the product's beside them, each with its
        # ask's shape, its hooks, and its check of an ask if it has one; a
        # name registered twice is refused. A product's kinds read the
        # managers built here, so each edge is bound at call time.
        return ResourceKinds(
            (
                *(ResourceKindSpec(name, ASK_PAYLOADS[name], hooks) for name, hooks in own.items()),
                *self._product.resources(lambda: self.managers),
            )
        )

    def key_service(self, keys: KeyServiceInterface) -> KeyServiceInterface:
        return KeyServiceByTenantImpl(self._keys)

    def purged(self, purge: SessionPurge) -> SessionPurge:
        park_alerts = self._storage.get_park_alert_storage()

        async def purged(org_id: UUID, agent_session_id: UUID, tree_id: UUID | None) -> None:
            # What the windows, the tools, attribution, and the agents hold of
            # the session, then what the exec relay, the evidence, the agent
            # projects, and the park alerts hold: its relayed exec items with
            # their output, its runs, its agent project's row, and who was
            # told it waits. The park alerts are built over these managers by
            # the processes that tell, so their rows are reached through
            # their storage.
            await purge(org_id, agent_session_id, tree_id)
            await self.managers.exec_relay.purge_agent_session(org_id, agent_session_id)
            await self.managers.evidence.purge_agent_session(org_id, agent_session_id)
            await self.managers.agent_projects.purge_agent_session(org_id, agent_session_id)
            batch = ParkAlertsOptions().purge_batch
            while await park_alerts.purge_agent_session(org_id, agent_session_id, batch):
                pass

        return purged

    def agent_sessions(
        self,
        sessions: AgentSessionsManagerInterface,
        *,
        steps: AgentStepsManagerInterface,
        privacy: PrivacyManagerInterface,
        tenancy: TenancyManagerInterface,
        events: ChangeEventsManagerInterface,
        outbox: OutboxRelayInterface,
    ) -> AgentSessionsManagerInterface:
        storage = self._storage
        options = self._options
        self._steps = steps
        self._privacy = privacy
        self._tenancy = tenancy
        self._outbox = outbox
        # A session's agent project, which its workspace binds and its
        # retention narrows by: outside `local`, a port that answers none for
        # every session is refused, so no per-agent-project policy silently
        # never applies.
        bound = options.workspace_agent_projects or WorkspaceAgentProjectsBoundImpl(
            storage.get_agent_project_storage()
        )
        narrowed = options.agent_session_projects or SessionAgentProjectBoundImpl(
            storage.get_agent_project_storage()
        )
        refuse_quiet_nulls(self._environment, bound, narrowed)
        # Each session's workspace, pinned as the session is created: a
        # decorator below pins it before the session is written. Its checkout
        # runs in the workspace through the transport the tools take, under
        # the session's epoch. Source control writes only through an
        # installation of the forge the session's tenant connected, read from
        # intake's rows.
        integrations = self._integrations
        writes = options.source_control or (
            SourceControlAbsentImpl()
            if integrations is None
            else SourceControlForgeImpl(
                integrations.get_integration, storage.get_intake_storage().read_installation_org
            )
        )
        # What a session delivered is read from its repository, and what it
        # has not from the workspace this process holds for it.
        self._held = HeldWorkspaces()
        workspaces_options = options.agent_workspaces_options or AgentWorkspacesOptions()
        self._agent_workspaces = AgentWorkspacesManagerImpl(
            storage.get_agent_workspace_storage(),
            tenancy,
            outbox,
            self._kinds,
            bound,
            options.pull_requests or PullRequestsNullImpl(),
            options.workspace_git
            or WorkspaceGitTransportImpl(self._placed, self._records, GitOptions(), writes),
            options.workspace_reader
            or RepositoryReaderGitImpl(
                walled=workspace_rules.NEVER_REACHED
                + workspace_rules.networks(workspaces_options.internal_networks),
                on_disk=self._environment == LOCAL,
            ),
            workspaces_options,
            self._infra.get_secrets(),
            writes,
            self._held,
            workspace_bases=WORKSPACE_BASE_KINDS | self._product.workspace_bases,
        )
        self._products = options.work_product or WorkProductAgentWorkspacesImpl(
            self._agent_workspaces, self._held
        )
        # Each session's retention: the snapshot it takes as it is created,
        # and the sweep that destroys its key when its content expires and
        # marks it when its shape does, through the engine's own sessions.
        # Every other namespace reaches the sessions through the decorator, so
        # no session is created without its snapshot.
        self._retention = RetentionManagerImpl(
            storage.get_retention_storage(),
            self._keys,
            privacy,
            sessions,
            tenancy,
            events,
            outbox,
            narrowed,
            options.retention_options or RetentionOptions(),
        )
        retained = AgentSessionsRetainedImpl(sessions, self._retention, privacy)
        # Each session's agent project: a session spawned or handed over
        # belongs to the agent project of the session it came from. And each
        # session's workspace pinned once its agent project row stands,
        # before its snapshot. Every other namespace reaches the sessions
        # through the decorators, so no such session stands outside its
        # origin's agent project, or unpinned.
        self._sessions = AgentSessionsInAgentProjectImpl(
            AgentSessionsPinnedImpl(
                retained, self._agent_workspaces, self._retention.keeps_at_rest
            ),
            storage.get_agent_project_storage(),
        )
        return self._sessions

    def pricing(self, gate: SpendBudgetGateInterface) -> PricingInterface | None:
        refuse_quiet_nulls(self._environment, self._storage.get_spend_ledger_storage())
        # Behind agent billing's gate, the one source of prices is the price
        # book, read by version, so a call held at one is billed at it.
        if isinstance(gate, MoneyGateInterface):
            self._book = PriceBookTableImpl()
        return self._book

    def call_gate(
        self,
        gate: SpendBudgetGateInterface,
        pricing: PricingInterface,
        sessions: AgentSessionsManagerInterface,
        budgets: SpendBudgetsManagerInterface,
        language_models_layer: LanguageModelsLayer | None,
    ) -> CallGateInterface:
        # The place each call's tokens and spend are counted and its usage
        # recorded, by the version and the tier the layer reads.
        version = None if language_models_layer is None else language_models_layer.version
        tier = None if language_models_layer is None else language_models_layer.tier
        if self._book is None or not isinstance(gate, MoneyGateInterface):
            return CallGateSpendBudgetImpl(
                gate,
                pricing,
                sessions,
                budgets,
                self._session_policies,
                version=version,
                tier=tier,
            )
        return MoneyCallGateImpl(
            gate,
            self._book,
            sessions,
            budgets,
            self._session_policies,
            version=version,
            tier=tier,
        )

    def catalog(self, catalog: tuple[ToolInterface, ...]) -> None:
        if self._options.platform_agents is not None:
            # The kinds that may only read are held to it over the whole
            # catalog, the engine's tools included.
            refuse_reach(self._agent_kinds, catalog)

    def transport(self, transport: TransportInterface) -> TransportInterface:
        return self._placed

    @property
    def fork_points(self) -> ForkPoints | None:
        # A fork of a workspace a host holds is taken by that host; the pins
        # are built over the engine's tools, so the edge is bound at call time.
        return lambda ctx, request, workspace, epoch: self._held_to_pins.fork_point(
            ctx, request, workspace, epoch
        )

    def tools(
        self, tools: ToolsManagerInterface, *, snapshots: SnapshotStore
    ) -> ToolsManagerInterface:
        storage = self._storage
        infra = self._infra
        options = self._options
        environment = self._environment
        tenancy = self._tenancy
        agent_workspaces = self._agent_workspaces
        # A session inside its tenant's wall finds its workspace on its host,
        # where only the relayed transport reaches. The exec relay and the
        # hosts are built after, so the edges are bound at call time.
        placed_workspaces = PlacedWorkspacesRelayedImpl(
            lambda: self.managers.exec_relay, lambda: self.managers.hosts
        )
        # The cloud pool: a machine per session of the cloud whose workspace
        # is a VM, its host reached through the exec relay as any host is.
        # Every process builds it: the gateway trades a machine's key, the
        # sweep lets its machines go, and the runner starts them, on the
        # machines infra chose.
        sessions_rows = storage.get_agent_session_storage()
        orgs_rows = storage.get_tenancy_storage()

        async def session_gone(org_id: UUID, agent_session_id: UUID) -> bool:
            # A deleted tenant's machines go at the next sweep, never at its
            # purge alone: a machine bills while it runs.
            org = await orgs_rows.read_org(org_id)
            if org is None or org.deleted_at is not None:
                return True
            session = await sessions_rows.read_session(org_id, agent_session_id)
            return session is None or session.deleted_at is not None

        self._cloud_pool = CloudPoolManagerImpl(
            storage.get_cloud_pool_storage(),
            infra.get_vms(),
            infra.get_seeds(),
            lambda: self.managers.hosts,
            lambda: placed_workspaces,
            lambda: self.managers.exec_relay,
            options.cloud_pool_options or CloudPoolOptions(),
            session_gone=session_gone,
            expired=tenancy.tenant_expired,
            stage=options.cloud_pool_stage,
        )
        # Each workspace is held to its session's pin, refused by this host
        # where it cannot give it, brought up to the session's branch, kept
        # before it goes, and let go by the run that holds it alone.
        self._held_to_pins = ToolsManagerAgentWorkspacesImpl(
            tools,
            agent_workspaces,
            self._steps,
            options.workspace_host or HostOffer(),
            local=environment == LOCAL,
            held=self._held,
            placed=None if options.transport_layer is None else placed_workspaces,
            snapshots=snapshots,
            # A snapshot a host keeps is named by the digest it declared, keyed
            # by the session; its revoked key asks the host to let it go.
            keyed_hash=self._privacy.keyed_hash,
            erase_on_host=lambda ctx, agent_session_id, host_id: self.managers.exec_relay.ask_erase(
                ctx, agent_session_id, host_id
            ),
            # So does the session's purge, which runs for no principal.
            erase_purged=lambda org_id, agent_session_id, host_id: (
                self.managers.exec_relay.erase_purged(org_id, agent_session_id, host_id)
            ),
            cloud=self._cloud_pool,
        )
        # What makes a result: the runs, the policies, and validation on the
        # executor, apart from every agent's workspace. Outside `local`, it is
        # the platform's own: an instance made for each run. For a session of
        # the cloud, it is the cloud's, on the provider and the transport
        # infra chose. For a session inside its tenant's wall, a host of its
        # pool makes it to the session's pinned isolation, and the exec relay
        # reaches it; the exec relay is built after, so the edge is bound at
        # call time. Either way, a session pinned to a base has its checks run
        # on that base, the tenant's workspace base the engine's tools build.
        executor = options.executor
        if executor is None and environment != LOCAL:
            hosts_storage = storage.get_hosts_storage()
            bases = AgentWorkspaceBases(
                infra.get_buckets(),
                infra.get_agent_workspaces(),
                infra.get_transport(),
                infra.get_cache(CacheScope.AGENT_WORKSPACE_BASE),
                snapshots.scan,
                self._tool_options.base_build_limit,
                self._tool_options.purge_batch,
                utcnow,
            )

            async def pinned(ctx: TenantContext, agent_session_id: UUID) -> Pin | None:
                if await inside_wall(hosts_storage, sessions_rows, ctx.org_id, agent_session_id):
                    return Pin(
                        (await agent_workspaces.get_workspace(ctx, agent_session_id)).spec(),
                        walled=True,
                    )
                try:
                    kept = await agent_workspaces.get_workspace(ctx, agent_session_id)
                except NotFound:
                    return None
                return Pin(kept.spec(), walled=False)

            executor = ExecutorAgentWorkspacesImpl(
                infra.get_agent_workspaces(),
                infra.get_transport(),
                agent_workspaces.checks_tree,
                pinned,
                PlacedInstancesRelayedImpl(
                    lambda: self.managers.exec_relay,
                    lambda stage: TransportRelayImpl(lambda: self.managers.exec_relay, stage),
                ),
                options.executor_options,
                bases=bases.archive,
            )
        self._evidence = EvidenceManagerImpl(
            storage.get_evidence_storage(),
            tenancy,
            self._outbox,
            Executors(executor or ExecutorAbsentImpl(), self._product.executors),
            self._products,
            self._session_policies,
            options.evidence_options or EvidenceOptions(),
        )
        held: ToolsManagerInterface = self._held_to_pins
        return held if options.tools_layer is None else options.tools_layer(held)

    def result_gate(self, gate: ResultGateInterface | None) -> ResultGateInterface | None:
        results = gate or ResultGateEvidenceImpl(
            self._storage.get_evidence_storage(), self._products, self._session_policies
        )
        refuse_quiet_nulls(self._environment, results, self._products)
        if self._options.platform_agents is None:
            return results
        # A reviewer's result is judged by the reads and findings it cites;
        # every other result passes the gate above, unchanged.
        return ResultGateReviewImpl(results, self._sessions, self._steps)

    def agents(self, agents: AgentsManagerInterface) -> AgentsManagerInterface:
        layer = self._options.agents_layer
        return agents if layer is None else layer(agents)

    @property
    def attached(self) -> AttachedToolsetsInterface:
        return self._options.attached_toolsets or AttachedToolsetsNoneImpl()

    def build(self, managers: Managers) -> PlatformManagers:
        """The platform's managers over the engine's, which `build_managers`
        built with these hooks, handed back beside them."""
        storage = self._storage
        infra = self._infra
        options = self._options
        tenancy = managers.tenancy
        outbox = managers.outbox
        placing = options.placement_options or PlacementOptions()
        hosting = options.hosts_options or HostsOptions()
        placement = PlacementManagerImpl(
            storage.get_placement_storage(),
            managers.work,
            tenancy,
            placing,
            self._work_kinds,
            self._claimant_kinds,
        )
        # A host's credential, its claims through placement, and where each
        # session runs. An exec item a claim takes is started by the exec
        # relay before it reaches a host, and the work that waits on a revoked
        # host is ended by it; the exec relay is built below, so both edges are
        # bound at call time.
        hosts = HostsManagerImpl(
            storage.get_hosts_storage(),
            PlacementClaimsRelayedImpl(placement, lambda: self.managers.exec_relay),
            managers.agent_sessions,
            tenancy,
            outbox,
            hosting,
            self._claimant_kinds,
            revoked=lambda rctx, org_id, host_id: self.managers.exec_relay.end_host(
                rctx, org_id, host_id
            ),
        )
        # The agent projects start a root session through the agents, under
        # an agent project of the caller's tenant, and answer each session's
        # agent project to the namespaces that key a policy by it.
        agent_projects = AgentProjectsManagerImpl(
            storage.get_agent_project_storage(),
            managers.agent_sessions,
            managers.agents,
            tenancy,
            outbox,
            options.agent_projects_options or AgentProjectsOptions(),
        )
        self._built = PlatformManagers(
            **vars(managers),
            retention=self._retention,
            evidence=self._evidence,
            placement=placement,
            # The work queue's operator plane writes a tenant's own cap on a
            # lane, and placement's writes it for a share too.
            placement_operator=PlacementOperatorManagerImpl(
                storage.get_placement_storage(),
                storage.get_tenancy_storage(),
                storage.get_change_event_storage(),
                infra.get_topics(),
                storage.get_agent_session_storage(),
                storage.get_work_storage(),
                storage.get_hosts_storage(),
                managers.work_operator,
                PlacementOperatorOptions(
                    default_tier=placing.default_tier,
                    tier_shares=placing.tier_shares,
                    default_share=placing.default_share,
                    online_window=hosting.online_window,
                ),
            ),
            agent_workspaces=self._agent_workspaces,
            hosts=hosts,
            # A tool call into a customer's wall as keyed exec work: its items,
            # their output sealed under the session's key as its commands'
            # records are, and the control messages that stop them.
            exec_relay=ExecRelayManagerImpl(
                storage.get_exec_relay_storage(),
                managers.work,
                managers.steps,
                tenancy,
                hosts,
                agent_projects,
                outbox,
                self._records,
                options.relay_options or ExecRelayOptions(),
                # A snapshot a host answers is recorded where it lives.
                kept=self._held_to_pins.keep_on_host,
            ),
            cloud_pool=self._cloud_pool,
            # The validation sessions: platform work on the queue, with no
            # agent.
            platform_agents=PlatformAgentsManagerImpl(
                storage.get_platform_agents_storage(),
                tenancy,
                outbox,
                self._evidence,
                options.platform_agents_options or PlatformAgentsOptions(),
            ),
            agent_projects=agent_projects,
            benchmarks=BenchmarksManagerImpl(storage.get_benchmark_storage()),
            kinds=self._kinds,
        )
        return self._built


def build_platform_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    operator_options: TenancyOperatorOptions | None = None,
    integrations: IntegrationsInterface | None = None,
    *,
    platform_root_options: PlatformRootOptions | None = None,
    **engine: Unpack[EngineOptions],
) -> PlatformManagers:
    """Every manager of the engine and the platform, in dependency order: the
    engine's root builds its graph with the platform's hooks, and the
    platform's managers are built over it. The engine's keywords are as
    `build_managers` takes them; `platform_root_options` is what the process
    sets on the platform's managers, None the defaults."""
    root = RootHooksPlatformImpl(
        storage, infra, integrations, platform_root_options or PlatformRootOptions(), engine
    )
    return root.build(
        build_managers(
            storage,
            infra,
            tenancy_options,
            operator_options,
            integrations,
            hooks=root,
            **root.engine_options(),
        )
    )
