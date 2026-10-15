"""Where a layer above the engine reaches the graph the business-layer root
builds (`acme.om.root.build_managers`): the kinds its work queue and its
leases read, the key service its sessions' keys are wrapped by, a face over
the sessions, the tools, and the agents, the gates a model call and a
result pass, the transport the tools run on, the toolsets a session holds
beyond its kind, and what goes with a purged session.

The root calls each hook once, in the order it builds, so an impl may keep
what an earlier hook handed it for a later one. `RootHooksNullImpl` reaches
nothing: the root builds the engine's graph as it is. The platform's impl is
`acme.om.platform_root.RootHooksPlatformImpl`."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

from acme.infra.keys import KeyServiceInterface
from acme.infra.transports import TransportInterface
from acme.om.agent_projects.impl.policies import SessionAgentProjectsNoneImpl
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps import AgentStepsManagerInterface
from acme.om.agents import AgentsManagerInterface, ResultGateInterface
from acme.om.agents.attached import AttachedToolsetsInterface, AttachedToolsetsNoneImpl
from acme.om.change_events import ChangeEventsManagerInterface
from acme.om.language_models.layer import LanguageModelsLayer
from acme.om.leases.hooks import LeasableResourceKindInterface
from acme.om.leases.kinds import ResourceKinds, ResourceKindSpec
from acme.om.leases.types.request import ASK_PAYLOADS
from acme.om.outbox import OutboxRelayInterface
from acme.om.privacy import PrivacyManagerInterface
from acme.om.spend_budgets import SpendBudgetGateInterface, SpendBudgetsManagerInterface
from acme.om.spend_budgets.pricing import PricingInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tools import ToolsManagerInterface
from acme.om.tools.impl.manager import ForkPoints
from acme.om.tools.impl.snapshots import SnapshotStore
from acme.om.tools.tool import ToolInterface
from acme.om.windows.gate import CallGateInterface
from acme.om.windows.impl.gate import CallGateSpendBudgetImpl
from acme.om.work.impl.manager import Lanes
from acme.om.work.kinds import WORK_KINDS, WorkKinds

SessionPurge = Callable[[UUID, UUID, UUID | None], Awaitable[None]]
"""What goes with a session the sweep purges, given its org, its id, and its
tree when it was the tree's last session."""


class RootHooksInterface(ABC):
    @property
    @abstractmethod
    def work_kinds(self) -> WorkKinds:
        """The kinds the work queue reads every item through."""
        ...

    @property
    @abstractmethod
    def lanes(self) -> Lanes | None:
        """The lane each item goes to, asked at every enqueue; None keeps the
        lane the item came with."""
        ...

    @abstractmethod
    def resource_kinds(self, own: Mapping[str, LeasableResourceKindInterface]) -> ResourceKinds:
        """The resource kinds the leases read: the mechanism's `own`, each with
        the shape of its ask, and the layer's beside them."""
        ...

    @abstractmethod
    def key_service(self, keys: KeyServiceInterface) -> KeyServiceInterface:
        """The key service each session's keys are wrapped by, over infra's
        `keys`."""
        ...

    @abstractmethod
    def purged(self, purge: SessionPurge) -> SessionPurge:
        """What goes with a purged session: the engine's `purge`, and what the
        layer holds of the session."""
        ...

    @abstractmethod
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
        """The sessions every manager built after them reaches: `sessions`, or
        a face over them that sees each session made. The privacy manager
        keeps `sessions` itself."""
        ...

    @abstractmethod
    def pricing(self, gate: SpendBudgetGateInterface) -> PricingInterface | None:
        """The one source of prices behind `gate`; None is the list table."""
        ...

    @abstractmethod
    def call_gate(
        self,
        gate: SpendBudgetGateInterface,
        pricing: PricingInterface,
        sessions: AgentSessionsManagerInterface,
        budgets: SpendBudgetsManagerInterface,
        language_models_layer: LanguageModelsLayer | None,
    ) -> CallGateInterface:
        """The gate every model call passes when the root is handed none,
        priced from `pricing`, counted under the version and the tier
        `language_models_layer` reads."""
        ...

    @abstractmethod
    def catalog(self, catalog: tuple[ToolInterface, ...]) -> None:
        """Refuses at boot a catalog the layer's kinds cannot run with
        (`UnsafeConfiguration`)."""
        ...

    @abstractmethod
    def transport(self, transport: TransportInterface) -> TransportInterface:
        """The transport the tools run commands on, over infra's."""
        ...

    @property
    @abstractmethod
    def fork_points(self) -> ForkPoints | None:
        """The layer's own fork point for a call's workspace; None takes every
        fork through the engine's provider."""
        ...

    @abstractmethod
    def tools(
        self, tools: ToolsManagerInterface, *, snapshots: SnapshotStore
    ) -> ToolsManagerInterface:
        """The tools the agents, the loop, and the root take: `tools`, or a
        face over them."""
        ...

    @abstractmethod
    def result_gate(self, gate: ResultGateInterface | None) -> ResultGateInterface | None:
        """The gate a result passes, over the one the root was handed; None is
        the null gate, which accepts a result and marks it unverified."""
        ...

    @abstractmethod
    def agents(self, agents: AgentsManagerInterface) -> AgentsManagerInterface:
        """The agents the loop and the root take: `agents`, or a face over
        them that sees each session made."""
        ...

    @property
    @abstractmethod
    def attached(self) -> AttachedToolsetsInterface:
        """The toolsets a session holds beyond its kind, which the loop folds
        in at each run."""
        ...


class RootHooksNullImpl(RootHooksInterface):
    """Reaches nothing: the work namespace's own kinds, the mechanism's own
    resource kinds, infra's key service and transport, the managers as they
    are built, the list table's prices, a call gate that keys no budget by
    agent project, the gate the root was handed, and nothing attached."""

    @property
    def work_kinds(self) -> WorkKinds:
        return WorkKinds(WORK_KINDS)

    @property
    def lanes(self) -> Lanes | None:
        return None

    def resource_kinds(self, own: Mapping[str, LeasableResourceKindInterface]) -> ResourceKinds:
        return ResourceKinds(
            ResourceKindSpec(name, ASK_PAYLOADS[name], hooks) for name, hooks in own.items()
        )

    def key_service(self, keys: KeyServiceInterface) -> KeyServiceInterface:
        return keys

    def purged(self, purge: SessionPurge) -> SessionPurge:
        return purge

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
        return sessions

    def pricing(self, gate: SpendBudgetGateInterface) -> PricingInterface | None:
        return None

    def call_gate(
        self,
        gate: SpendBudgetGateInterface,
        pricing: PricingInterface,
        sessions: AgentSessionsManagerInterface,
        budgets: SpendBudgetsManagerInterface,
        language_models_layer: LanguageModelsLayer | None,
    ) -> CallGateInterface:
        return CallGateSpendBudgetImpl(
            gate,
            pricing,
            sessions,
            budgets,
            SessionAgentProjectsNoneImpl(),
            version=None if language_models_layer is None else language_models_layer.version,
            tier=None if language_models_layer is None else language_models_layer.tier,
        )

    def catalog(self, catalog: tuple[ToolInterface, ...]) -> None:
        return None

    def transport(self, transport: TransportInterface) -> TransportInterface:
        return transport

    @property
    def fork_points(self) -> ForkPoints | None:
        return None

    def tools(
        self, tools: ToolsManagerInterface, *, snapshots: SnapshotStore
    ) -> ToolsManagerInterface:
        return tools

    def result_gate(self, gate: ResultGateInterface | None) -> ResultGateInterface | None:
        return gate

    def agents(self, agents: AgentsManagerInterface) -> AgentsManagerInterface:
        return agents

    @property
    def attached(self) -> AttachedToolsetsInterface:
        return AttachedToolsetsNoneImpl()
