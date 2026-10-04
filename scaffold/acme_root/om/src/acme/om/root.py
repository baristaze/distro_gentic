"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from acme.infra.base import QuietNull
from acme.infra.cache import CacheInterface, CacheScope
from acme.infra.root import InfraInterface
from acme.infra.transports import TransportInterface
from acme.infra.workspaces import IsolationSpec
from acme.integrations.identity import IdentityProviderInterface
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.model_providers.registry import absent_model_providers
from acme.integrations.root import IntegrationsInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_sessions.impl.manager import AgentSessionsManagerImpl, AgentSessionsOptions
from acme.om.agents import AgentsManagerInterface, ResultGateInterface
from acme.om.agents.impl.loop import LoopManagerImpl, LoopOptions
from acme.om.agents.impl.manager import AgentsManagerImpl, AgentsOptions
from acme.om.agents.impl.sink import StreamSinkNullImpl
from acme.om.agents.loop import LoopManagerInterface
from acme.om.agents.sink import StreamSinkInterface
from acme.om.agents.types.kind import AgentKind, AgentKindCatalog
from acme.om.attribution import AttributionManagerInterface, PrincipalContext
from acme.om.attribution.impl.manager import (
    AttributionManagerImpl,
    AttributionOptions,
    members_context,
)
from acme.om.automations.actions import AutomationActionInterface
from acme.om.base import utcnow
from acme.om.benchmarks import BenchmarksManagerInterface
from acme.om.benchmarks.impl.manager import BenchmarksManagerImpl
from acme.om.billing.gate import MoneyGateInterface
from acme.om.billing.impl.gate import MoneyCallGateImpl
from acme.om.billing.impl.prices import PriceBookTableImpl
from acme.om.budgets import (
    BudgetGateInterface,
    BudgetsManagerInterface,
    BudgetsOperatorManagerInterface,
)
from acme.om.budgets.impl.gate import BudgetGateImpl, BudgetGateOptions
from acme.om.budgets.impl.manager import BudgetsManagerImpl, BudgetsOptions
from acme.om.budgets.impl.operator import BudgetsOperatorManagerImpl, BudgetsOperatorOptions
from acme.om.budgets.impl.pricing import PricingTableImpl
from acme.om.budgets.pricing import PricingInterface
from acme.om.context import TenantContext
from acme.om.events import EventsManagerInterface
from acme.om.events.impl.manager import EventsManagerImpl, EventsOptions
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
from acme.om.exceptions import Unavailable, UnsafeConfiguration
from acme.om.hosts import HostsManagerInterface
from acme.om.hosts.impl.manager import HostsManagerImpl, HostsOptions
from acme.om.hosts.impl.placement import inside_wall
from acme.om.hosts.rules import ENROLLMENT_PREFIX
from acme.om.idempotency import IdempotencyManagerInterface
from acme.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from acme.om.intake import IntakeManagerInterface
from acme.om.knowledge import KnowledgeManagerInterface
from acme.om.media import MediaManagerInterface
from acme.om.media.impl.manager import MediaManagerImpl, MediaOptions
from acme.om.models.impl.credentials import CallCredentialsPlatformImpl
from acme.om.models.impl.manager import ModelsManagerImpl, ModelsOptions
from acme.om.models.impl.prices import ModelPricesFromPricingImpl
from acme.om.models.impl.resolver import ModelResolverTableImpl, ResolverOptions
from acme.om.models.layer import ModelsLayer
from acme.om.models.manager import ModelsManagerInterface
from acme.om.models.prices import ModelPricesInterface
from acme.om.orchestrations import OrchestrationsManagerInterface
from acme.om.orchestrations.impl.manager import OrchestrationsManagerImpl, OrchestrationsOptions
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.impl.relay import OutboxRelayImpl
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
from acme.om.platform_agents.catalog import PlatformAgents, refuse_reach, with_shipped
from acme.om.platform_agents.impl.manager import PlatformAgentsManagerImpl, PlatformAgentsOptions
from acme.om.platform_agents.kinds import SHIPPED
from acme.om.privacy import PrivacyManagerInterface
from acme.om.privacy.impl.artifacts import ArtifactSealKeysImpl
from acme.om.privacy.impl.keys import SessionKeysImpl
from acme.om.privacy.impl.manager import PrivacyManagerImpl, PrivacyOptions
from acme.om.privacy.impl.memory_only_steps import StepStorageShapeOnlyImpl
from acme.om.privacy.impl.records import RecordSealKeysImpl
from acme.om.privacy.impl.routed_steps import StepStorageRoutedImpl
from acme.om.privacy.impl.sealed_steps import StepStorageSealedImpl
from acme.om.privacy.keys import SessionKeysInterface
from acme.om.projects import ProjectsManagerInterface
from acme.om.projects.impl.manager import ProjectsManagerImpl, ProjectsOptions
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.projects.impl.retention import SessionProjectBoundImpl
from acme.om.projects.impl.sessions import AgentSessionsInProjectImpl
from acme.om.projects.policies import SessionProjectsInterface
from acme.om.relay import RelayManagerInterface
from acme.om.relay.impl.instances import PlacedInstancesRelayedImpl
from acme.om.relay.impl.manager import RelayManagerImpl, RelayOptions
from acme.om.relay.impl.placement import PlacementClaimsRelayedImpl
from acme.om.relay.impl.transport import TransportRelayImpl
from acme.om.relay.impl.workspaces import PlacedWorkspacesRelayedImpl
from acme.om.retention import RetentionManagerInterface
from acme.om.retention.impl.keys import (
    KeyServiceByTenantImpl,
    KeyServiceLocalImpl,
    TenantKeysImpl,
)
from acme.om.retention.impl.manager import RetentionManagerImpl, RetentionOptions
from acme.om.retention.impl.sessions import AgentSessionsRetainedImpl
from acme.om.retention.keys import TenantKeysInterface
from acme.om.retention.projects import SessionProjectInterface
from acme.om.steps import StepsManagerInterface
from acme.om.steps.impl.manager import StepsManagerImpl, StepsOptions
from acme.om.steps.storage import StepStorageInterface
from acme.om.steps.storage.impl.memory import StepStorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy import TenancyManagerInterface, TenancyOperatorManagerInterface
from acme.om.tenancy.impl.credentials import TenancyCredentialsManagerImpl
from acme.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from acme.om.tenancy.impl.members import TenancyMembersManagerImpl
from acme.om.tenancy.impl.operator import TenancyOperatorManagerImpl, TenancyOperatorOptions
from acme.om.tenancy.impl.org import TenancyOrgManagerImpl
from acme.om.tenancy.impl.sign_in import TenancySignInManagerImpl
from acme.om.tenancy.rules import CREDENTIAL_PREFIXES
from acme.om.tenancy.storage import TenancyStorageInterface
from acme.om.tools import ToolRegistry, ToolsManagerInterface
from acme.om.tools.attachments import AttachmentReaderInterface
from acme.om.tools.impl.attachments import AttachmentReaderNullImpl
from acme.om.tools.impl.manager import ToolsManagerImpl, ToolsOptions
from acme.om.tools.native.ask_person import AskPersonToolImpl
from acme.om.tools.native.read_attachment import ReadAttachmentToolImpl
from acme.om.tools.native.write_plan import WritePlanToolImpl
from acme.om.tools.seal import RecordSealInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import Decision, PolicyLayer, PolicyRule
from acme.om.tools.types.tool import ToolClass
from acme.om.trust.owners import SecretOwnerInterface
from acme.om.watch.kinds import StreamKind
from acme.om.windows import WindowsManagerInterface
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.hashes import PromptHashInterface
from acme.om.windows.impl.gate import CallGateBudgetImpl
from acme.om.windows.impl.hashes import PromptHashPrivacyImpl
from acme.om.windows.impl.manager import WindowsManagerImpl, WindowsOptions
from acme.om.windows.seal import ArtifactSealInterface
from acme.om.windows.types.policy import CompactionPolicy
from acme.om.work import WorkManagerInterface, WorkOperatorManagerInterface
from acme.om.work.impl.manager import WorkManagerImpl, WorkOptions
from acme.om.work.impl.operator import WorkOperatorManagerImpl
from acme.om.work.kinds import WorkKindSpec
from acme.om.workspaces import WorkspacesManagerInterface
from acme.om.workspaces import rules as workspace_rules
from acme.om.workspaces.git import RepositoryReaderInterface, WorkspaceGitInterface
from acme.om.workspaces.impl.executor import ExecutorOptions, ExecutorWorkspacesImpl
from acme.om.workspaces.impl.forge import SourceControlAbsentImpl, SourceControlForgeImpl
from acme.om.workspaces.impl.git import GitOptions, WorkspaceGitTransportImpl
from acme.om.workspaces.impl.manager import WorkspacesManagerImpl, WorkspacesOptions
from acme.om.workspaces.impl.projects import PullRequestsNullImpl, WorkspaceProjectsBoundImpl
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.workspaces.impl.sessions import AgentSessionsPinnedImpl
from acme.om.workspaces.impl.tools import HeldWorkspaces, ToolsManagerWorkspacesImpl
from acme.om.workspaces.impl.work_product import WorkProductWorkspacesImpl
from acme.om.workspaces.projects import (
    PullRequestsInterface,
    SourceControlInterface,
    WorkspaceProjectsInterface,
)
from acme.om.workspaces.types.host import HostOffer


@dataclass(frozen=True)
class Managers:
    tenancy: TenancyManagerInterface
    tenancy_operator: TenancyOperatorManagerInterface
    work: WorkManagerInterface
    work_operator: WorkOperatorManagerInterface
    media: MediaManagerInterface
    idempotency: IdempotencyManagerInterface
    events: EventsManagerInterface
    outbox: OutboxRelayInterface
    orchestrations: OrchestrationsManagerInterface
    steps: StepsManagerInterface
    agent_sessions: AgentSessionsManagerInterface
    privacy: PrivacyManagerInterface
    retention: RetentionManagerInterface
    budgets: BudgetsManagerInterface
    budgets_operator: BudgetsOperatorManagerInterface
    budget_gate: BudgetGateInterface
    pricing: PricingInterface
    models: ModelsManagerInterface
    windows: WindowsManagerInterface
    attribution: AttributionManagerInterface
    agents: AgentsManagerInterface
    tools: ToolsManagerInterface
    loop: LoopManagerInterface
    evidence: EvidenceManagerInterface
    placement: PlacementManagerInterface
    placement_operator: PlacementOperatorManagerInterface
    workspaces: WorkspacesManagerInterface
    hosts: HostsManagerInterface
    relay: RelayManagerInterface
    platform_agents: PlatformAgentsManagerInterface
    projects: ProjectsManagerInterface
    benchmarks: BenchmarksManagerInterface


ProductTools = Callable[[Callable[[], Managers]], tuple[ToolInterface, ...]]
"""A product's tools, built over the managers as the root answers them once
it has built them: a tool keeps the callable and reads a manager through it
when it is called, as the platform's own tools do."""


def no_tools(managers: Callable[[], Managers]) -> tuple[ToolInterface, ...]:
    """A product with no tools of its own."""
    return ()


ProductActions = Callable[[Callable[[], Managers]], tuple[AutomationActionInterface, ...]]
"""A product's own kinds of automation action, built over the managers as
the root answers them, as a product's tools are."""


def no_actions(managers: Callable[[], Managers]) -> tuple[AutomationActionInterface, ...]:
    """A product with no automation action of its own."""
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
    claimant kind of its own that writes it, if any; its executors, by
    the validation environment each runs; and its kinds of automation
    action, each acting in a firing, saying when the run it started
    ended, and checking the person who writes one (`automations.actions`). Its agent kinds join the platform's
    catalog, which refuses a version declared twice, and its tools the
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

    def __post_init__(self) -> None:
        for spec in self.work:
            if spec.claimant is None:
                raise ValueError(f"{spec.name} names no claimant kind, so nothing would claim it")
        # A stream a claimant writes is bound to an item it holds, and only a
        # product's claimant holds one: the host's items are the relay's.
        own = {claimant.name for claimant in self.claimants}
        for stream in self.streams:
            if stream.claimant is not None and stream.claimant not in own:
                raise ValueError(
                    f"stream kind {stream.name} is written by {stream.claimant}, "
                    "which is no claimant kind of the product's"
                )


@dataclass(frozen=True)
class PlatformPorts:
    """The platform's ports a product hands each of its roots, each None for
    the platform's own: billing's money gate as the budget gate, the
    evidence's result gate over the work product, the platform's executor
    (the loud null in `local`), the workspaces' work product, and the
    projects' rows for a session's project, which its workspace binds and
    its retention narrows by. Outside `local`, a root refuses a quiet null
    for any of them. `kinds` is what the product adds to the platform's
    kinds, so every root reads the one registry: none adds nothing. Each
    process's entry point hands its root `PRODUCT_KINDS`
    (`acme.om.product_kinds`), where a product declares them once."""

    budget_gate: BudgetGateInterface | None = None
    result_gate: ResultGateInterface | None = None
    executor: ExecutorInterface | None = None
    work_product: WorkProductInterface | None = None
    session_projects: SessionProjectInterface | None = None
    workspace_projects: WorkspaceProjectsInterface | None = None
    kinds: ProductKinds = field(default_factory=ProductKinds)


PLATFORM_PREFIXES = (*CREDENTIAL_PREFIXES, ENROLLMENT_PREFIX, workspace_rules.PUSH_TOKEN_PREFIX)
"""The prefixes of the platform's credentials that are no claimant's: a
person's and an operator's, an enrollment token's, and a push token's. A
claimant kind's prefix is none of them, so a prefix names one kind."""

LOCAL = "local"
"""The one environment a root accepts a quiet null budget gate, ledger,
result gate, or platform port in."""


def refuse_quiet_nulls(environment: str, *capabilities: object) -> None:
    """Outside `local`, a root refuses a quiet null budget gate, ledger,
    result gate, or platform port at boot: every model call would pass a
    gate that holds nothing, and spend outside every budget, every success
    would end unverified, and a policy keyed by a session's project would
    never apply. A loud null is no such risk: it refuses each call itself."""
    if environment == LOCAL:
        return
    for capability in capabilities:
        if isinstance(capability, QuietNull):
            raise UnsafeConfiguration(
                f"{type(capability).__name__} holds nothing, and is refused "
                f"when the environment is {environment}"
            )


def product_ceilings(platform: PolicyLayer, product: ProductKinds) -> PolicyLayer:
    """The platform's ceilings with the product's beside them, one rule per
    class the product declares a ceiling for. A ceiling of a class the
    platform's engine knows, of a class the product does not declare, or of
    a class a platform ceiling already names is refused at boot, so a
    product caps its own classes and never touches the platform's."""
    platform_classes = {rule.authorization_class for rule in platform.rules}
    rules: list[PolicyRule] = []
    for name, decision in product.ceilings.items():
        if name in {known.value for known in ToolClass}:
            raise ValueError(f"{name} is a platform class, and its ceiling is the platform's")
        if name not in product.classes:
            raise ValueError(f"a ceiling names {name}, which is no class of the product's")
        if name in platform_classes:
            raise ValueError(f"the platform already holds a ceiling for {name}")
        rules.append(PolicyRule(authorization_class=name, decision=decision))
    return PolicyLayer(rules=(*platform.rules, *rules))


def intake_absent() -> IntakeManagerInterface:
    """No intake in this process: a loud null, so a tool that binds its
    session's work refuses rather than act where no event can find it."""
    raise Unavailable("no intake binds a session's work in this process")


def knowledge_absent() -> KnowledgeManagerInterface:
    """No knowledge in this process: a loud null, so a tool that searches,
    reads, or suggests knowledge refuses rather than answer that none is
    kept."""
    raise Unavailable("no knowledge is kept in this process")


async def purge_held(
    managers: Managers, org_id: UUID, session_id: UUID, tree_id: UUID | None
) -> None:
    """What the windows, the tools, the relay, attribution, the evidence, the
    projects, and the agents hold of a session the sweep purges: its
    artifacts, its workspace with its transport's records, and its relayed
    exec items with their output, which go with its history,
    its authority, its runs, its project's row, and its tree when it was
    the tree's last session."""
    await managers.windows.purge_artifacts(org_id, session_id)
    await managers.tools.purge_workspace(org_id, session_id)
    await managers.relay.purge_session(org_id, session_id)
    await managers.attribution.purge_authority(org_id, session_id)
    await managers.evidence.purge_session(org_id, session_id)
    await managers.projects.purge_session(org_id, session_id)
    if tree_id is not None:
        await managers.agents.purge_tree(org_id, tree_id)


def build_tenancy(
    storage: TenancyStorageInterface,
    relay: OutboxRelayInterface,
    cache: CacheInterface,
    options: TenancyOptions,
    clock: Callable[[], datetime] = utcnow,
    *,
    identity_provider: IdentityProviderInterface,
) -> TenancyManagerInterface:
    """The tenancy manager with its delegates, each built here and handed to
    it: a caller outside the namespace reaches a delegate through the
    manager, and no impl builds another. A delegate that calls a sibling
    takes it here, by its interface, and one that needs an operation of the
    manager takes that one operation as a callable. `clock` is the one the
    second factor's time step is read from."""
    sign_in = TenancySignInManagerImpl(
        storage, relay, options, clock, identity_provider=identity_provider
    )
    # The account's deletion writes a row under each place its person holds,
    # and a stage comes only from the manager's transition. The manager holds
    # this delegate, so that one edge is bound at call time.
    org = TenancyOrgManagerImpl(
        storage,
        relay,
        options,
        identity_provider=identity_provider,
        service_context=lambda rctx, org_id, user_id: tenancy.service_context(
            rctx, org_id, user_id
        ),
    )
    members = TenancyMembersManagerImpl(
        storage, relay, options, org=org, identity_provider=identity_provider
    )
    credentials = TenancyCredentialsManagerImpl(storage, relay, options)
    tenancy = TenancyManagerImpl(
        storage,
        relay,
        cache,
        options,
        sign_in=sign_in,
        org=org,
        members=members,
        credentials=credentials,
    )
    return tenancy


def private_history(
    storage: StorageInterface, keys: SessionKeysInterface, transient: StepStorageInterface
) -> StepStorageInterface:
    """The history as the engine reaches it: every session routed by its
    storage policy to content sealed at rest, to a shape at rest and its
    content in this process, or to nothing at rest (`transient`). Each impl
    is wired here, at boot; the steps manager sees one interface."""
    history = storage.get_step_storage()
    return StepStorageRoutedImpl(
        sealed=StepStorageSealedImpl(history, keys),
        shape_only=StepStorageShapeOnlyImpl(history),
        transient=transient,
        policies=storage.get_privacy_storage(),
    )


def build_managers(
    storage: StorageInterface,
    infra: InfraInterface,
    tenancy_options: TenancyOptions | None = None,
    operator_options: TenancyOperatorOptions | None = None,
    integrations: IntegrationsInterface | None = None,
    *,
    media_options: MediaOptions | None = None,
    idempotency_options: IdempotencyOptions | None = None,
    events_options: EventsOptions | None = None,
    work_options: WorkOptions | None = None,
    orchestrations_options: OrchestrationsOptions | None = None,
    steps_options: StepsOptions | None = None,
    agent_sessions_options: AgentSessionsOptions | None = None,
    budgets_options: BudgetsOptions | None = None,
    models_options: ModelsOptions | None = None,
    model_prices: ModelPricesInterface | None = None,
    models_layer: ModelsLayer | None = None,
    call_gate: CallGateInterface | None = None,
    prompt_hash: PromptHashInterface | None = None,
    artifact_seal: ArtifactSealInterface | None = None,
    record_seal: RecordSealInterface | None = None,
    compaction_policy: CompactionPolicy | None = None,
    agents_options: AgentsOptions | None = None,
    attribution_options: AttributionOptions | None = None,
    agent_kinds: tuple[AgentKind, ...] = (),
    principal_context: PrincipalContext | None = None,
    result_gate: ResultGateInterface | None = None,
    tools_options: ToolsOptions | None = None,
    tools_layer: Callable[[ToolsManagerInterface], ToolsManagerInterface] | None = None,
    budget_gate: BudgetGateInterface | None = None,
    stream_sink: StreamSinkInterface | None = None,
    tool_catalog: tuple[ToolInterface, ...] = (),
    attachment_reader: AttachmentReaderInterface | None = None,
    domain_classes: tuple[str, ...] = (),
    loop_options: LoopOptions | None = None,
    placement_options: PlacementOptions | None = None,
    workspaces_options: WorkspacesOptions | None = None,
    workspace_host: HostOffer | None = None,
    workspace_projects: WorkspaceProjectsInterface | None = None,
    pull_requests: PullRequestsInterface | None = None,
    source_control: SourceControlInterface | None = None,
    workspace_git: WorkspaceGitInterface | None = None,
    workspace_reader: RepositoryReaderInterface | None = None,
    hosts_options: HostsOptions | None = None,
    relay_options: RelayOptions | None = None,
    transport_layer: Callable[[TransportInterface], TransportInterface] | None = None,
    platform_agents_options: PlatformAgentsOptions | None = None,
    platform_agents: PlatformAgents | None = None,
    intake: Callable[[], IntakeManagerInterface] | None = None,
    knowledge: Callable[[], KnowledgeManagerInterface] | None = None,
    environment: str = LOCAL,
    tenant_keys: TenantKeysInterface | None = None,
    session_projects: SessionProjectInterface | None = None,
    session_policies: SessionProjectsInterface | None = None,
    retention_options: RetentionOptions | None = None,
    evidence_options: EvidenceOptions | None = None,
    executor: ExecutorInterface | None = None,
    executor_options: ExecutorOptions | None = None,
    work_product: WorkProductInterface | None = None,
    projects_options: ProjectsOptions | None = None,
    product_kinds: ProductKinds | None = None,
) -> Managers:
    """`integrations` is the root of the hosted services the managers front:
    the identity provider, which the tenancy manager signs people in and
    invites them through. None is a process that signs nobody in, and every
    call that would reach the provider is refused as unavailable.

    The options after `integrations` are what the process that sweeps sets
    on the managers it purges through: each one's retention and batch. None
    keeps that manager's defaults.

    `model_prices` is what the resolver asks before it picks a model. None
    asks the one source of prices, the budgets' list table, so a model with
    no row of its own resolves nowhere.

    `models_layer` is a layer's own models: its resolver in place of the
    table, a face over the models manager every namespace reaches, the
    client each model call runs on, and the version each session is pinned
    to and its tenant's plan tier, which its calls' tokens and spend count
    under. None keeps the engine's: the table, the manager as it is, every
    call on the platform's key, and every call counted under `none`.

    `call_gate` is the budget gate every model call passes, the loop's and a
    compaction's, and `prompt_hash` the key service's hash a request's
    header records. None wires the budgets' gate behind the one, and the
    privacy namespace's keyed hash behind the other. `budget_gate` None is
    the gate over the ledger; billing's money gate puts billing's call gate
    behind the one, priced from the price book by version. Outside
    `environment` `local`, a quiet null gate or ledger is refused at boot
    (`UnsafeConfiguration`).
    `artifact_seal` is what seals an artifact's text under its session's
    key, and `record_seal` what seals a command's output in its transport's
    record; None wires the privacy namespace's seal over the session keys.
    `compaction_policy` None keeps the default policy.

    Three are the adopter's for its agents: `agent_kinds`, every version of
    each kind it still runs; `principal_context`, the transition of its
    tenancy manager that answers for a principal's live permissions, which
    every tool call asks; and `result_gate`, the gate a result passes. None
    wires the tenancy manager's own, which answers for a person by the
    membership they hold at the call and for no service principal, and the
    evidence's gate over `work_product`. Outside `environment` `local`, a
    quiet null result gate or work product is refused at boot
    (`UnsafeConfiguration`).

    The loop takes the rest: `tool_catalog`, the adopter's tools, after the
    engine's own (`engine_tools`), of which a session's registry holds those
    its kind names; a tool of the adopter's that takes an engine tool's name
    is refused. `attachment_reader` is what reads an attachment's text for
    the engine's read tool, None the null that refuses. Then
    `domain_classes`, the classes the adopter declares; `stream_sink`, the
    carrier its parts go to, None the quiet null, which drops them; and
    `loop_options`. Its outage signal is infra's, and its model providers
    the integrations'.

    The evidence takes the platform's two ports: `executor`, the fresh
    executor validation runs on, and `work_product`, which reads what a
    session delivered, and which the result gate reads too. None wires the
    platform's executor, a fresh instance of the cloud's for each run, made
    and recorded as `executor_options` say, the image the process's
    workspaces run among them, or in `local` the loud null, which refuses
    every validation; and the
    workspaces' work product, the session's branch as its repository holds it, with the
    workspace this process holds for the session telling what was not
    delivered; one it does not hold, or one of no bound repository, is
    refused, so no success counts on a guess. Whatever
    `tools_options` names, the tools take the platform's ceiling on a
    protected path beside its ceilings, and the product's on its own
    classes.

    `tools_layer` wraps the tools manager before the loop and the root take
    it: a layer above the engine holds its own rules around every call, and
    sees each call the engine runs. None takes the tools manager as it is.

    `product_kinds` is what a product adds to the platform's kinds
    (`PlatformPorts.kinds`): its agent kinds, tools, classes, and their
    ceilings, which join `agent_kinds`, `tool_catalog`, `domain_classes`,
    and the tools' ceilings, each tool
    reading the managers built here at call time; its work kinds and
    claimant kinds, which the work queue and placement read beside the
    platform's; and its executors, which run a check that names their
    environment. A name the platform holds is refused at boot. None adds
    nothing.

    `placement_options` is the fair share of a tenant no operator gave one,
    and the delay a loop over its share waits; None keeps the defaults.
    `hosts_options` is the lives of a host's credentials, the window a host
    counts as online, and its claim's lease; None keeps the defaults.
    `relay_options` is the lease a host renews on an `exec` item and the
    bounds of its output; None keeps the defaults. `transport_layer` wraps
    the transport infra chose before the tools and the checkout take it:
    the session runner puts the relay behind it for a session inside its
    tenant's wall, whose workspace is then the one a host of its pool
    prepared and holds. None takes infra's transport as it is, and makes
    every workspace on this machine.

    `platform_agents` ships the platform's agents, with the corpus its
    assistant answers from: their kinds join `agent_kinds` and their tools
    join `tool_catalog`, ahead of the adopter's. A catalog that holds two
    tools of one name, or lets the assistant reach past reading and handing
    work on, is refused at boot (`UnsafeConfiguration`). None ships none.
    `intake` answers the intake the process builds over these managers,
    where the engineer's pull request is bound to its session; None binds
    nothing, so that tool opens none. `knowledge` answers the knowledge the
    process builds over them, which the agents search, read, and suggest
    to; None keeps none, so those tools refuse.

    The platform's retention takes three. `tenant_keys` says whose key
    service holds each tenant's keys; None is infra's for every tenant, and
    in `local` the local key service over it, which destroys a session's key
    and reports it as a tenant's own service does. Elsewhere infra's holds
    the tenant's key alone, and the engine's revocation is the
    destruction. `session_projects` names a new session's project; None
    reads the row the projects' start wrote, and a session with no row
    takes its tenant's policy unnarrowed (a quiet null one is refused
    outside `local`); and
    `retention_options` the sweep's batches.

    The platform's projects take `projects_options`, the purges' batch.
    `session_policies` answers a session's project to the gate's budgets
    and to the evidence's policy; None reads the projects' rows, and a
    session with no row is charged to no project and judged by no policy.

    The workspaces take six. `workspace_host` is what this process, the
    host its tools run on, offers beyond its provider; None offers nothing
    more, as a host of the platform's cloud. `workspace_projects` answers a
    session's project and the repository it binds (a quiet null one is
    refused outside `local`), and `pull_requests` why a session's branch is
    gone; None reads the projects' rows for the one,
    and knows no pull request, so a branch gone for any reason fails
    loudly. `source_control` opens a session's branch and pull request;
    None writes through the forge integration, and with no integrations,
    nowhere. `workspace_git` runs the checkout; None runs it in the
    workspace through the transport the tools take, so a workspace inside
    a tenant's wall is checked out there, from bundles the reader brings
    and source control pushes. `workspace_reader` reads what a
    session delivered from its repository; None fetches it into a fresh
    repository of this process's own, with the project's fetch credential,
    never from a network no workspace reaches, and from disk in `local`
    alone. `workspaces_options` names those networks, and the sweep's
    batch."""
    # The kinds every manager reads through: the platform's own, and the
    # product's beside them. A product's tools read the managers built
    # below, as the platform's own do, so each edge is bound at call time.
    product = product_kinds or ProductKinds()
    agent_kinds = (*agent_kinds, *product.agents)
    tool_catalog = (*tool_catalog, *product.tools(lambda: managers))
    domain_classes = (*domain_classes, *product.classes)
    if platform_agents is not None:
        # Their tools read the managers built below, so each edge is bound
        # at call time.
        agent_kinds = (*SHIPPED, *agent_kinds)
        tool_catalog = with_shipped(
            platform_agents,
            tool_catalog,
            domain_classes,
            sessions=lambda: managers.agent_sessions,
            policies=lambda: managers.tools,
            agents=lambda: managers.agents,
            evidence=lambda: managers.evidence,
            workspaces=lambda: managers.workspaces,
            intake=intake or intake_absent,
            knowledge=knowledge or knowledge_absent,
        )
        refuse_reach(agent_kinds, tool_catalog)
    # The relay every core-role manager hands its outbox rows to. It reaches
    # the work manager through the root below, because a row of kind
    # `work.<kind>` is enqueued there: the work manager needs the tenancy
    # manager, which needs this relay, so that one edge is bound at call time
    # and the graph the root hands back is still whole.
    outbox = OutboxRelayImpl(
        storage.get_outbox_storage(),
        storage.get_event_storage(),
        infra.get_topics(),
        lambda: managers.work,
    )
    tenancy = build_tenancy(
        storage.get_tenancy_storage(),
        outbox,
        infra.get_cache(CacheScope.REALTIME_TICKET),
        tenancy_options or TenancyOptions(),
        identity_provider=(
            IdentityProviderAbsentImpl()
            if integrations is None
            else integrations.get_identity_provider()
        ),
    )
    events = EventsManagerImpl(
        storage.get_event_storage(), tenancy, events_options or EventsOptions()
    )
    work_kinds = platform_work_kinds().extended(product.work)
    claimant_kinds = ClaimantKinds(
        (*platform_claimant_kinds(), *product.claimants), reserved=PLATFORM_PREFIXES
    )
    work = WorkManagerImpl(
        storage.get_work_storage(),
        tenancy,
        events,
        infra.get_topics(),
        work_options or WorkOptions(),
        work_kinds,
        # Every item goes to the lane where its environment is, which
        # placement answers. Placement claims through this manager, so it is
        # built below and the edge is bound at call time.
        lanes=lambda org_id, item: managers.placement.lane_for(org_id, item),
    )
    media = MediaManagerImpl(
        storage.get_media_storage(),
        infra.get_buckets(),
        tenancy,
        outbox,
        media_options or MediaOptions(),
    )
    orchestrations = OrchestrationsManagerImpl(
        storage.get_orchestrations_storage(),
        tenancy,
        outbox,
        orchestrations_options or OrchestrationsOptions(),
    )
    # The history first: a session's status is read off its steps. What a
    # step says reaches it through the sealing layer, by the session's policy.
    # Each tenant's keys in its own key service: the platform's, or the one
    # the tenant brought. In `local`, the platform's is the local key service
    # over infra's, which holds each session's key in this process.
    keys = tenant_keys or TenantKeysImpl(
        KeyServiceLocalImpl(infra.get_keys()) if environment == LOCAL else infra.get_keys()
    )
    session_keys = SessionKeysImpl(storage.get_privacy_storage(), KeyServiceByTenantImpl(keys))
    records = record_seal or RecordSealKeysImpl(session_keys, storage.get_privacy_storage())
    steps = StepsManagerImpl(
        private_history(storage, session_keys, StepStorageMemoryImpl()),
        tenancy,
        steps_options or StepsOptions(),
        # Who may instruct a session is the agents' to answer, from its
        # registry; they are built below on this manager, so the edge is
        # bound at call time.
        instructs=lambda ctx, session_id: managers.agents.require_instructor(ctx, session_id),
    )
    kinds = AgentKindCatalog(kinds=agent_kinds)
    # A session's project, which its workspace binds and its retention
    # narrows by: outside `local`, a port that answers none for every session
    # is refused, so no per-project policy silently never applies.
    bound = workspace_projects or WorkspaceProjectsBoundImpl(storage.get_project_storage())
    narrowed = session_projects or SessionProjectBoundImpl(storage.get_project_storage())
    refuse_quiet_nulls(environment, bound, narrowed)
    # The transport infra chose, and the one the tools and the checkout
    # take: for a session inside its tenant's wall, the relay to its host.
    transport = infra.get_transport()
    placed = transport if transport_layer is None else transport_layer(transport)
    # Each session's workspace, pinned as the session is created: a
    # decorator below pins it before the session is written. Its checkout
    # runs in the workspace through the transport the tools take, under the
    # session's epoch. Source control writes only through an installation of
    # the forge the session's tenant connected, read from intake's rows.
    writes = source_control or (
        SourceControlAbsentImpl()
        if integrations is None
        else SourceControlForgeImpl(
            integrations.get_integration, storage.get_intake_storage().read_installation_org
        )
    )
    # What a session delivered is read from its repository, and what it has
    # not from the workspace this process holds for it.
    held = HeldWorkspaces()
    workspaces_options = workspaces_options or WorkspacesOptions()
    workspaces = WorkspacesManagerImpl(
        storage.get_workspace_storage(),
        tenancy,
        outbox,
        kinds,
        bound,
        pull_requests or PullRequestsNullImpl(),
        workspace_git or WorkspaceGitTransportImpl(placed, records, GitOptions(), writes),
        workspace_reader
        or RepositoryReaderGitImpl(
            walled=workspace_rules.NEVER_REACHED
            + workspace_rules.networks(workspaces_options.internal_networks),
            on_disk=environment == LOCAL,
        ),
        workspaces_options,
        infra.get_secrets(),
        writes,
        held,
    )
    engine_sessions = AgentSessionsManagerImpl(
        storage.get_agent_session_storage(),
        steps,
        tenancy,
        outbox,
        agent_sessions_options or AgentSessionsOptions(),
        # What attribution and the agents hold of a purged session goes with
        # it. Both are built below on this manager, so the edge is bound at
        # call time.
        purged=lambda org_id, session_id, tree_id: purge_held(
            managers, org_id, session_id, tree_id
        ),
    )
    privacy = PrivacyManagerImpl(
        storage.get_privacy_storage(),
        session_keys,
        steps,
        engine_sessions,
        tenancy,
        outbox,
        PrivacyOptions(),
    )
    # Each session's retention: the snapshot it takes as it is created, and
    # the sweep that destroys its key when its content expires and marks it
    # when its shape does, through the engine's own sessions. Every other
    # namespace reaches the sessions through the decorator, so no session is
    # created without its snapshot.
    retention = RetentionManagerImpl(
        storage.get_retention_storage(),
        keys,
        privacy,
        engine_sessions,
        tenancy,
        events,
        outbox,
        narrowed,
        retention_options or RetentionOptions(),
    )
    retained = AgentSessionsRetainedImpl(engine_sessions, retention, privacy)
    # Each session's project: a session spawned or handed over belongs to
    # the project of the session it came from. And each session's workspace
    # pinned once its project row stands, before its snapshot. Every other
    # namespace reaches the sessions through the decorators, so no such
    # session stands outside its origin's project, or unpinned.
    agent_sessions = AgentSessionsInProjectImpl(
        AgentSessionsPinnedImpl(retained, workspaces), storage.get_project_storage()
    )
    # The gate reads the budgets of a call's scopes and holds on the ledger.
    budgets = BudgetsManagerImpl(
        storage.get_budget_storage(),
        storage.get_ledger_storage(),
        tenancy,
        outbox,
        budgets_options or BudgetsOptions(),
    )
    gate = budget_gate or BudgetGateImpl(
        storage.get_budget_storage(), storage.get_ledger_storage(), BudgetGateOptions()
    )
    refuse_quiet_nulls(
        environment, gate, storage.get_ledger_storage(), storage.get_money_ledger_storage()
    )
    # The one source of prices, which the resolver asks before it answers a
    # fill and the gate prices every call by. Behind billing's gate it is the
    # price book, read by version, so a call held at one is billed at it.
    book = PriceBookTableImpl() if isinstance(gate, MoneyGateInterface) else None
    pricing: PricingInterface = book or PricingTableImpl()
    # A session's fills. The resolver refuses a model with no price row of
    # its own.
    prices = model_prices or ModelPricesFromPricingImpl(pricing)
    models: ModelsManagerInterface = ModelsManagerImpl(
        storage.get_fill_set_storage(),
        steps,
        tenancy,
        (
            ModelResolverTableImpl(prices, ResolverOptions())
            if models_layer is None
            else models_layer.resolver(prices)
        ),
        models_options or ModelsOptions(),
    )
    if models_layer is not None:
        models = models_layer.models(models, tenancy)
    attribution = AttributionManagerImpl(
        storage.get_attribution_storage(),
        agent_sessions,
        steps,
        principal_context or members_context(tenancy),
        tenancy,
        outbox,
        attribution_options or AttributionOptions(),
    )
    products = work_product or WorkProductWorkspacesImpl(workspaces, held)
    # A budget and a validation policy set per project are read through the
    # session's project.
    session_policies = session_policies or SessionProjectsBoundImpl(storage.get_project_storage())
    results = result_gate or ResultGateEvidenceImpl(
        storage.get_evidence_storage(), products, session_policies
    )
    refuse_quiet_nulls(environment, results, products)
    catalog = engine_tools(steps, attachment_reader or AttachmentReaderNullImpl()) + tool_catalog
    ToolRegistry(catalog, domain_classes)  # refuses two tools of one name at boot
    # What a model request reads: rendered from the history, compacted by
    # the summarizer through the model providers, behind the gate, paid for
    # by the spender attribution names.
    providers = (
        absent_model_providers() if integrations is None else integrations.get_model_providers()
    )
    # The key each call goes out on: the platform's, unless a layer says.
    credentials = (
        CallCredentialsPlatformImpl(providers, (loop_options or LoopOptions()).credential)
        if models_layer is None
        else models_layer.credentials(providers)
    )
    # The one gate every model call passes, priced from the one source, and
    # the place each call's tokens and spend are counted and its usage
    # recorded.
    version = None if models_layer is None else models_layer.version
    tier = None if models_layer is None else models_layer.tier
    calls = call_gate or (
        CallGateBudgetImpl(
            gate, pricing, agent_sessions, budgets, session_policies, version=version, tier=tier
        )
        if book is None or not isinstance(gate, MoneyGateInterface)
        else MoneyCallGateImpl(
            gate, book, agent_sessions, budgets, session_policies, version=version, tier=tier
        )
    )
    windows = WindowsManagerImpl(
        storage.get_window_storage(),
        steps,
        tenancy,
        models,
        attribution,
        credentials,
        infra.get_buckets(),
        calls,
        prompt_hash or PromptHashPrivacyImpl(privacy),
        artifact_seal or ArtifactSealKeysImpl(session_keys, storage.get_privacy_storage()),
        compaction_policy or CompactionPolicy(),
        WindowsOptions(),
    )
    # A child's report reaches its parent through windows, which bounds it.
    agents = AgentsManagerImpl(
        storage.get_agent_storage(),
        agent_sessions,
        steps,
        attribution,
        results,
        kinds,
        tenancy,
        outbox,
        agents_options or AgentsOptions(),
        budgets=budgets,
        windows=windows,
        tool_classes={tool.spec.name: tool.spec.authorization_class for tool in catalog},
        secret_tools=frozenset(tool.spec.name for tool in catalog if tool.spec.secrets),
    )
    # Where the engine touches the world: the session's history for a
    # person's decisions, the events for the audit of each secret a call
    # uses, the workspace and the transport infra chose, and attribution,
    # which answers whose authority each call runs under and the rule of
    # two. What a call keeps of its session's content goes under the
    # session's key: its input's hash, and its command's record.
    # The ceilings: the options' own, the platform's on a protected path,
    # and the product's on its own classes.
    tool_options = tools_options or ToolsOptions()
    ceilings = tool_options.ceilings
    if PROTECTED_CEILING not in ceilings.rules:
        ceilings = PolicyLayer(rules=(*ceilings.rules, PROTECTED_CEILING))
    ceilings = product_ceilings(ceilings, product)
    tool_options = tool_options.model_copy(update={"ceilings": ceilings})
    engine_tools_manager = ToolsManagerImpl(
        storage.get_tool_storage(),
        steps,
        tenancy,
        events,
        outbox,
        infra.get_workspaces(),
        placed,
        tool_options,
        keyed_hash=privacy.keyed_hash,
        record_seal=records,
        attribution=attribution,
    )
    # Each workspace is held to its session's pin, refused by this host where
    # it cannot give it, brought up to the session's branch, kept before it
    # goes, and let go by the run that holds it alone.
    tools: ToolsManagerInterface = ToolsManagerWorkspacesImpl(
        engine_tools_manager,
        workspaces,
        steps,
        workspace_host or HostOffer(),
        local=environment == LOCAL,
        held=held,
        # A session inside its tenant's wall finds its workspace on its
        # host, where only the relayed transport reaches. The relay and the
        # hosts are built below, so the edges are bound at call time.
        placed=None
        if transport_layer is None
        else PlacedWorkspacesRelayedImpl(lambda: managers.relay, lambda: managers.hosts),
    )
    # What makes a result: the runs, the policies, and validation on the
    # executor, apart from every agent's workspace. Outside `local`, it is
    # the platform's own: an instance made for each run. For a session of
    # the cloud, it is the cloud's, on the provider and the transport infra
    # chose. For a session inside its tenant's wall, a host of its pool
    # makes it to the session's pinned isolation, and the relay reaches it;
    # the relay is built below, so the edge is bound at call time.
    if executor is None and environment != LOCAL:
        hosts_storage = storage.get_hosts_storage()
        sessions_storage = storage.get_agent_session_storage()

        async def pinned(ctx: TenantContext, session_id: UUID) -> IsolationSpec | None:
            if not await inside_wall(hosts_storage, sessions_storage, ctx.org_id, session_id):
                return None
            return (await workspaces.get_workspace(ctx, session_id)).spec()

        executor = ExecutorWorkspacesImpl(
            infra.get_workspaces(),
            transport,
            workspaces.checks_tree,
            pinned,
            PlacedInstancesRelayedImpl(
                lambda: managers.relay,
                lambda stage: TransportRelayImpl(lambda: managers.relay, stage),
            ),
            executor_options,
        )
    evidence = EvidenceManagerImpl(
        storage.get_evidence_storage(),
        tenancy,
        outbox,
        Executors(executor or ExecutorAbsentImpl(), product.executors),
        products,
        session_policies,
        evidence_options or EvidenceOptions(),
    )
    if tools_layer is not None:
        tools = tools_layer(tools)
    idempotency = IdempotencyManagerImpl(
        storage.get_idempotency_storage(), idempotency_options or IdempotencyOptions()
    )
    tenancy_operator = TenancyOperatorManagerImpl(
        storage.get_tenancy_storage(),
        storage.get_event_storage(),
        outbox,
        operator_options or TenancyOperatorOptions(),
    )
    placement = PlacementManagerImpl(
        storage.get_placement_storage(),
        work,
        tenancy,
        placement_options or PlacementOptions(),
        work_kinds,
        claimant_kinds,
    )
    # A host's credential, its claims through placement, and where each
    # session runs. An exec item a claim takes is started by the relay before
    # it reaches a host; the relay is built below, so the edge is bound at
    # call time.
    hosts = HostsManagerImpl(
        storage.get_hosts_storage(),
        PlacementClaimsRelayedImpl(placement, lambda: managers.relay),
        agent_sessions,
        tenancy,
        outbox,
        hosts_options or HostsOptions(),
        claimant_kinds,
    )
    # The validation sessions: platform work on the queue, with no agent.
    platform = PlatformAgentsManagerImpl(
        storage.get_platform_agents_storage(),
        tenancy,
        outbox,
        evidence,
        platform_agents_options or PlatformAgentsOptions(),
    )
    # The projects start a root session through the agents, under a project
    # of the caller's tenant, and answer each session's project to the
    # namespaces that key a policy by it.
    projects = ProjectsManagerImpl(
        storage.get_project_storage(),
        agent_sessions,
        agents,
        tenancy,
        outbox,
        projects_options or ProjectsOptions(),
    )
    managers = Managers(
        tenancy=tenancy,
        tenancy_operator=tenancy_operator,
        work=work,
        work_operator=WorkOperatorManagerImpl(
            storage.get_work_storage(),
            storage.get_tenancy_storage(),
            storage.get_event_storage(),
            infra.get_topics(),
        ),
        media=media,
        idempotency=idempotency,
        events=events,
        outbox=outbox,
        orchestrations=orchestrations,
        steps=steps,
        agent_sessions=agent_sessions,
        privacy=privacy,
        retention=retention,
        budgets=budgets,
        budgets_operator=BudgetsOperatorManagerImpl(
            storage.get_ledger_storage(), storage.get_tenancy_storage(), BudgetsOperatorOptions()
        ),
        budget_gate=gate,
        # The one source of prices: the list table.
        pricing=pricing,
        models=models,
        windows=windows,
        attribution=attribution,
        agents=agents,
        tools=tools,
        # The loop, over every namespace above: what the engine does while
        # the model chooses.
        loop=LoopManagerImpl(
            steps,
            agent_sessions,
            agents,
            kinds,
            attribution,
            models,
            windows,
            tools,
            calls,
            credentials,
            infra.get_outages(),
            stream_sink or StreamSinkNullImpl(),
            catalog,
            loop_options or LoopOptions(),
            domain_classes=domain_classes,
        ),
        evidence=evidence,
        placement=placement,
        placement_operator=PlacementOperatorManagerImpl(
            storage.get_placement_storage(),
            storage.get_tenancy_storage(),
            storage.get_event_storage(),
            infra.get_topics(),
            storage.get_agent_session_storage(),
            storage.get_work_storage(),
            storage.get_hosts_storage(),
            PlacementOperatorOptions(
                default_tier=(placement_options or PlacementOptions()).default_tier,
                default_concurrency=(placement_options or PlacementOptions()).default_concurrency,
                online_window=(hosts_options or HostsOptions()).online_window,
            ),
        ),
        workspaces=workspaces,
        hosts=hosts,
        # A tool call into a customer's wall as keyed exec work: its items,
        # their output sealed under the session's key as its commands' records
        # are, and the control messages that stop them.
        relay=RelayManagerImpl(
            storage.get_relay_storage(),
            work,
            steps,
            tenancy,
            hosts,
            projects,
            outbox,
            records,
            relay_options or RelayOptions(),
        ),
        platform_agents=platform,
        projects=projects,
        benchmarks=BenchmarksManagerImpl(storage.get_benchmark_storage()),
    )
    return managers


def engine_tools(
    steps: StepsManagerInterface, attachments: AttachmentReaderInterface
) -> tuple[ToolInterface, ...]:
    """The tools the engine ships, offered to a session only when its kind
    names them: asking its person or standing down, writing its plan, and
    reading an attachment by range."""
    return (AskPersonToolImpl(), WritePlanToolImpl(), ReadAttachmentToolImpl(steps, attachments))
