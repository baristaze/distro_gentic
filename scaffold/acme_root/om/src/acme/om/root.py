"""The business-layer root: constructs every manager in dependency order and
hands back one frozen object with a field per manager."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from acme.infra.base import QuietNull
from acme.infra.cache import CacheInterface, CacheScope
from acme.infra.root import InfraInterface
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
from acme.om.base import utcnow
from acme.om.budgets import BudgetGateInterface, BudgetsManagerInterface
from acme.om.budgets.impl.gate import BudgetGateImpl, BudgetGateOptions
from acme.om.budgets.impl.manager import BudgetsManagerImpl, BudgetsOptions
from acme.om.budgets.impl.pricing import PricingTableImpl
from acme.om.budgets.pricing import PricingInterface
from acme.om.events import EventsManagerInterface
from acme.om.events.impl.manager import EventsManagerImpl, EventsOptions
from acme.om.evidence import (
    EvidenceManagerInterface,
    ExecutorInterface,
    WorkProductInterface,
)
from acme.om.evidence.impl.gate import ResultGateEvidenceImpl
from acme.om.evidence.impl.manager import EvidenceManagerImpl, EvidenceOptions
from acme.om.evidence.impl.ports import ExecutorAbsentImpl, WorkProductAbsentImpl
from acme.om.evidence.rules import PROTECTED_CEILING
from acme.om.exceptions import UnsafeConfiguration
from acme.om.idempotency import IdempotencyManagerInterface
from acme.om.idempotency.impl.manager import IdempotencyManagerImpl, IdempotencyOptions
from acme.om.media import MediaManagerInterface
from acme.om.media.impl.manager import MediaManagerImpl, MediaOptions
from acme.om.models.impl.manager import ModelsManagerImpl, ModelsOptions
from acme.om.models.impl.prices import ModelPricesFromPricingImpl
from acme.om.models.impl.resolver import ModelResolverTableImpl, ResolverOptions
from acme.om.models.manager import ModelsManagerInterface
from acme.om.models.prices import ModelPricesInterface
from acme.om.orchestrations import OrchestrationsManagerInterface
from acme.om.orchestrations.impl.manager import OrchestrationsManagerImpl, OrchestrationsOptions
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.impl.relay import OutboxRelayImpl
from acme.om.placement import PlacementManagerInterface, PlacementOperatorManagerInterface
from acme.om.placement.impl.manager import PlacementManagerImpl, PlacementOptions
from acme.om.placement.impl.operator import PlacementOperatorManagerImpl
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
from acme.om.projects.impl.sessions import AgentSessionsInProjectImpl
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
from acme.om.tenancy.storage import TenancyStorageInterface
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.impl.manager import ToolsManagerImpl, ToolsOptions
from acme.om.tools.seal import RecordSealInterface
from acme.om.tools.tool import ToolInterface
from acme.om.tools.types.policy import PolicyLayer
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
    budgets: BudgetsManagerInterface
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
    projects: ProjectsManagerInterface


LOCAL = "local"
"""The one environment a root accepts a quiet null budget gate, ledger, or
result gate in."""


def refuse_quiet_nulls(environment: str, *capabilities: object) -> None:
    """Outside `local`, a root refuses a quiet null budget gate, ledger, or
    result gate at boot: every model call would pass a gate that holds
    nothing, and spend outside every budget, and every success would end
    unverified. A loud null is no such risk: it refuses each call itself."""
    if environment == LOCAL:
        return
    for capability in capabilities:
        if isinstance(capability, QuietNull):
            raise UnsafeConfiguration(
                f"{type(capability).__name__} holds nothing, and is refused "
                f"when the environment is {environment}"
            )


async def purge_held(
    managers: Managers, org_id: UUID, session_id: UUID, tree_id: UUID | None
) -> None:
    """What the windows, the tools, attribution, the evidence, the projects,
    and the agents hold of a session the sweep purges: its artifacts, and
    its workspace with its transport's records, which go with its history,
    its authority, its runs, its project's row, and its tree when it was
    the tree's last session."""
    await managers.windows.purge_artifacts(org_id, session_id)
    await managers.tools.purge_workspace(org_id, session_id)
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
    domain_classes: tuple[str, ...] = (),
    loop_options: LoopOptions | None = None,
    placement_options: PlacementOptions | None = None,
    environment: str = LOCAL,
    evidence_options: EvidenceOptions | None = None,
    executor: ExecutorInterface | None = None,
    work_product: WorkProductInterface | None = None,
    projects_options: ProjectsOptions | None = None,
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

    `call_gate` is the budget gate every model call passes, the loop's and a
    compaction's, and `prompt_hash` the key service's hash a request's
    header records. None wires the budgets' gate behind the one, and the
    privacy namespace's keyed hash behind the other. `budget_gate` None is
    the gate over the ledger; outside `environment` `local`, a quiet null
    gate or ledger is refused at boot (`UnsafeConfiguration`).
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
    quiet null result gate is refused at boot (`UnsafeConfiguration`).

    The loop takes the rest: `tool_catalog`, the adopter's tools, of which a
    session's registry holds those its kind names, with `domain_classes`,
    the classes the adopter declares; `stream_sink`, the carrier its parts
    go to, None the quiet null, which drops them; and `loop_options`. Its
    outage signal is infra's, and its model providers the integrations'.

    The evidence takes the platform's two ports: `executor`, the fresh
    executor validation runs on, and `work_product`, which reads what a
    session delivered, and which the result gate reads too. None wires the
    loud nulls, which refuse every validation and every read, so no success
    counts until a process wires a work product. Whatever `tools_options`
    names, the tools take the platform's ceiling on a protected path beside
    its ceilings.

    `tools_layer` wraps the tools manager before the loop and the root take
    it: a layer above the engine holds its own rules around every call, and
    sees each call the engine runs. None takes the tools manager as it is.

    `placement_options` is the fair share of a tenant no operator gave one,
    and the delay a loop over its share waits; None keeps the defaults.

    The platform's projects take `projects_options`, the purges' batch."""
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
    work = WorkManagerImpl(
        storage.get_work_storage(),
        tenancy,
        events,
        infra.get_topics(),
        work_options or WorkOptions(),
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
    session_keys = SessionKeysImpl(storage.get_privacy_storage(), infra.get_keys())
    steps = StepsManagerImpl(
        private_history(storage, session_keys, StepStorageMemoryImpl()),
        tenancy,
        steps_options or StepsOptions(),
        # Who may instruct a session is the agents' to answer, from its
        # registry; they are built below on this manager, so the edge is
        # bound at call time.
        instructs=lambda ctx, session_id: managers.agents.require_instructor(ctx, session_id),
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
    # Each session's project: a session spawned or handed over belongs to
    # the project of the session it came from. Every other namespace reaches
    # the sessions through the decorator, so no such session stands outside
    # its origin's project.
    agent_sessions = AgentSessionsInProjectImpl(engine_sessions, storage.get_project_storage())
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
    refuse_quiet_nulls(environment, gate, storage.get_ledger_storage())
    # The one source of prices, which the resolver asks before it answers a
    # fill and the gate prices every call by.
    pricing = PricingTableImpl()
    # A session's fills. The resolver refuses a model with no price row of
    # its own.
    models = ModelsManagerImpl(
        storage.get_fill_set_storage(),
        steps,
        tenancy,
        ModelResolverTableImpl(
            model_prices or ModelPricesFromPricingImpl(pricing), ResolverOptions()
        ),
        models_options or ModelsOptions(),
    )
    attribution = AttributionManagerImpl(
        storage.get_attribution_storage(),
        agent_sessions,
        steps,
        principal_context or members_context(tenancy),
        tenancy,
        outbox,
        attribution_options or AttributionOptions(),
    )
    kinds = AgentKindCatalog(kinds=agent_kinds)
    products = work_product or WorkProductAbsentImpl()
    results = result_gate or ResultGateEvidenceImpl(storage.get_evidence_storage(), products)
    refuse_quiet_nulls(environment, results)
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
        tool_classes={tool.spec.name: tool.spec.authorization_class for tool in tool_catalog},
    )
    # What a model request reads: rendered from the history, compacted by
    # the summarizer through the model providers, behind the gate, paid for
    # by the spender attribution names.
    providers = (
        absent_model_providers() if integrations is None else integrations.get_model_providers()
    )
    # The one gate every model call passes, priced from the one source.
    calls = call_gate or CallGateBudgetImpl(gate, pricing, agent_sessions)
    windows = WindowsManagerImpl(
        storage.get_window_storage(),
        steps,
        tenancy,
        models,
        attribution,
        providers,
        infra.get_buckets(),
        calls,
        prompt_hash or PromptHashPrivacyImpl(privacy),
        artifact_seal or ArtifactSealKeysImpl(session_keys, storage.get_privacy_storage()),
        compaction_policy or CompactionPolicy(),
        WindowsOptions(),
    )
    # Where the engine touches the world: the session's history for a
    # person's decisions, the events for the audit of each secret a call
    # uses, the workspace and the transport infra chose, and attribution,
    # which answers whose authority each call runs under and the rule of
    # two. What a call keeps of its session's content goes under the
    # session's key: its input's hash, and its command's record.
    tool_options = tools_options or ToolsOptions()
    if PROTECTED_CEILING not in tool_options.ceilings.rules:
        ceilings = PolicyLayer(rules=(*tool_options.ceilings.rules, PROTECTED_CEILING))
        tool_options = tool_options.model_copy(update={"ceilings": ceilings})
    tools: ToolsManagerInterface = ToolsManagerImpl(
        storage.get_tool_storage(),
        steps,
        tenancy,
        events,
        outbox,
        infra.get_workspaces(),
        infra.get_transport(),
        tool_options,
        keyed_hash=privacy.keyed_hash,
        record_seal=record_seal or RecordSealKeysImpl(session_keys, storage.get_privacy_storage()),
        attribution=attribution,
    )
    # What makes a result: the runs, the policies, and validation on the
    # executor, apart from every agent's workspace.
    evidence = EvidenceManagerImpl(
        storage.get_evidence_storage(),
        tenancy,
        outbox,
        executor or ExecutorAbsentImpl(),
        products,
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
        budgets=budgets,
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
            providers,
            infra.get_outages(),
            stream_sink or StreamSinkNullImpl(),
            tool_catalog,
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
        ),
        projects=projects,
    )
    return managers
