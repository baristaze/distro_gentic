"""The trust swimlane over the engine's managers: the layer a root wraps
its tools in, and the trust managers built over the managers it returns.

    layer = TrustLayer(storage, infra, placement=..., probe=..., clients=...)
    managers = build_managers(storage, infra, ..., tools_layer=layer.tools)
    trust = layer.build(managers)

The layer is handed to the engine's root before the managers exist, and
the trust manager reads them, so its one edge to the trust manager is
bound at call time, as the engine binds its own."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from acme.infra.root import InfraInterface
from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.absent import ModelProviderAbsentImpl
from acme.integrations.model_providers.types import ProviderName
from acme.om.base import utcnow
from acme.om.privacy.impl.keys import SessionKeysImpl
from acme.om.projects.impl.policies import SessionProjectsBoundImpl
from acme.om.root import Managers, private_history
from acme.om.steps.storage.impl.memory import StepStorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tools.manager import ToolsManagerInterface
from acme.om.trust.impl.keys import ProviderClientsCachedImpl
from acme.om.trust.impl.manager import TrustManagerImpl, TrustOptions
from acme.om.trust.impl.operator import TrustOperatorManagerImpl
from acme.om.trust.impl.tools import ToolsManagerTrustedImpl
from acme.om.trust.keys import ClientFactory, KeyProbeInterface, ProviderClientsInterface
from acme.om.trust.manager import TrustManagerInterface
from acme.om.trust.operator import TrustOperatorManagerInterface
from acme.om.trust.placement import PlacementInterface


@dataclass(frozen=True)
class TrustManagers:
    trust: TrustManagerInterface
    trust_operator: TrustOperatorManagerInterface
    provider_clients: ProviderClientsInterface


def absent_client(provider: ProviderName, value: str) -> ModelProviderInterface:
    """The client of a root that builds none on a tenant's key: it refuses
    every call, loudly, and holds nothing of the key."""
    return ModelProviderAbsentImpl(provider, "no client is built on a tenant's own key")


def build_trust_operator(
    storage: StorageInterface,
    infra: InfraInterface,
    options: TrustOptions | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> TrustOperatorManagerInterface:
    """The operator plane of trust alone, over storage and the keys: what the
    API serves an operator, and what the grant job writes grants with. An
    operator's shape is read from the history at rest, never opened; content
    is opened as the engine opens it, by each session's key."""
    keys = SessionKeysImpl(storage.get_privacy_storage(), infra.get_keys())
    return TrustOperatorManagerImpl(
        storage.get_trust_storage(),
        storage.get_agent_session_storage(),
        storage.get_step_storage(),
        private_history(storage, keys, StepStorageMemoryImpl()),
        storage.get_event_storage(),
        options or TrustOptions(),
        clock,
    )


class TrustLayer:
    """`placement` answers where each session runs and on which machine
    credential; `probe` asks a provider about a key before it is saved; and
    `clients` builds a provider's client on a tenant's key. A session's
    project, which keeps a project's secrets to it, is read from the
    projects' rows."""

    def __init__(
        self,
        storage: StorageInterface,
        infra: InfraInterface,
        *,
        placement: PlacementInterface,
        probe: KeyProbeInterface,
        clients: ClientFactory = absent_client,
        options: TrustOptions | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._infra = infra
        self._placement = placement
        self._probe = probe
        self._clients = clients
        self.options = options or TrustOptions()
        self._clock = clock
        self._built: TrustManagers | None = None

    def tools(self, inner: ToolsManagerInterface) -> ToolsManagerInterface:
        """The engine's tools manager, held to the wall and audited."""
        return ToolsManagerTrustedImpl(inner, lambda: self.managers.trust, self._clock)

    def build(self, managers: Managers) -> TrustManagers:
        """The trust managers over the engine's, once; built again, the same."""
        if self._built is not None:
            return self._built
        storage = self._storage
        trust = TrustManagerImpl(
            storage.get_trust_storage(),
            managers.steps,
            managers.events,
            managers.attribution,
            managers.agent_sessions,
            managers.tenancy,
            managers.outbox,
            self._infra.get_secrets(),
            self._placement,
            SessionProjectsBoundImpl(storage.get_project_storage()),
            self._probe,
            self.options,
            self._clock,
        )
        operator = build_trust_operator(storage, self._infra, self.options, self._clock)
        clients = ProviderClientsCachedImpl(
            storage.get_trust_storage(),
            self._infra.get_secrets(),
            self._clients,
            use_grain=self.options.key_use_grain,
            clock=self._clock,
        )
        self._built = TrustManagers(trust=trust, trust_operator=operator, provider_clients=clients)
        return self._built

    @property
    def managers(self) -> TrustManagers:
        if self._built is None:
            raise RuntimeError("the trust layer is used before its managers are built")
        return self._built
