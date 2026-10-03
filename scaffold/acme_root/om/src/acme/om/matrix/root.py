"""The matrix swimlane over the engine's models: the layer a root hands the
engine's root, and the matrix managers built over the managers it returns.

    matrix = MatrixLayer(storage, options=MatrixOptions(environment=...),
                         clients=lambda: trust.managers.provider_clients)
    managers = build_managers(storage, infra, ..., models_layer=matrix.layer)
    built = matrix.build(managers)

The layer gives the engine four things: the matrix as its resolver, a face
over its models manager that resolves within the tenant's retention and
switches a retired model at the next loop, the key each call goes out on,
the tenant's own when it pays its providers, and the version each session
is pinned to, which its calls' tokens and spend count under."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from acme.integrations.model_providers import ModelProvidersInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.base import utcnow
from acme.om.context import TenantContext
from acme.om.matrix.impl.credentials import CallCredentialsByFundingImpl
from acme.om.matrix.impl.manager import MatrixManagerImpl, MatrixOperatorManagerImpl
from acme.om.matrix.impl.models import ModelsManagerMatrixImpl
from acme.om.matrix.impl.resolver import MatrixOptions, MatrixResolverImpl, Workload
from acme.om.matrix.manager import MatrixManagerInterface, MatrixOperatorManagerInterface
from acme.om.models.credentials import CallCredentialsInterface
from acme.om.models.impl.credentials import CallCredentialsPlatformImpl
from acme.om.models.impl.prices import ModelPricesFromPricingImpl
from acme.om.models.layer import ModelsLayer
from acme.om.models.manager import ModelsManagerInterface
from acme.om.models.prices import ModelPricesInterface
from acme.om.models.types.fill import MAIN, SUMMARIZER
from acme.om.platform_agents.kinds import SHIPPED
from acme.om.root import Managers
from acme.om.storage.root import StorageInterface
from acme.om.tenancy import TenancyManagerInterface
from acme.om.trust.keys import ProviderClientsInterface


@dataclass(frozen=True)
class MatrixManagers:
    matrix: MatrixManagerInterface
    matrix_operator: MatrixOperatorManagerInterface


class MatrixLayer:
    """`clients` serves a tenant's clients on its own keys, the trust
    layer's, bound at call time; None builds none, so a tenant on its own
    keys runs no call. `workload` names a session's workload class; None
    names every one `standard`. `kinds` are the product's own agent kinds,
    beside the ones the platform ships: a version of the matrix serves every
    model role any of them calls, and the engine's own two."""

    def __init__(
        self,
        storage: StorageInterface,
        *,
        options: MatrixOptions | None = None,
        clients: Callable[[], ProviderClientsInterface] | None = None,
        workload: Workload | None = None,
        kinds: Sequence[AgentKind] = (),
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._storage = storage
        self._required = frozenset(
            {MAIN, SUMMARIZER, *(role for kind in (*SHIPPED, *kinds) for role in kind.roles)}
        )
        self.options = options or MatrixOptions()
        self._clients = clients
        self._workload = workload
        self._clock = clock
        self._resolver: MatrixResolverImpl | None = None
        self._prices: ModelPricesInterface | None = None
        self._built: MatrixManagers | None = None

    @property
    def layer(self) -> ModelsLayer:
        """What the engine's root takes of the matrix."""
        return ModelsLayer(
            resolver=self.resolver,
            models=self.models,
            credentials=self.credentials,
            version=self.version,
        )

    def resolver(self, prices: ModelPricesInterface) -> MatrixResolverImpl:
        if self._resolver is None:
            storage = self._storage
            self._prices = prices
            self._resolver = MatrixResolverImpl(
                storage.get_matrix_storage(),
                storage.get_matrix_tenant_storage(),
                storage.get_agent_session_storage(),
                storage.get_placement_storage(),
                storage.get_account_storage(),
                storage.get_trust_storage(),
                prices,
                self.options,
                self._workload,
                self._clock,
            )
        return self._resolver

    def models(
        self, inner: ModelsManagerInterface, tenancy: TenancyManagerInterface
    ) -> ModelsManagerInterface:
        if self._resolver is None:
            raise RuntimeError("the matrix's face is built before its resolver")
        return ModelsManagerMatrixImpl(
            inner,
            self._resolver,
            self._storage.get_matrix_tenant_storage(),
            self._storage.get_retention_storage(),
            tenancy,
            self.options,
            self._clock,
        )

    async def version(self, ctx: TenantContext, session_id: UUID) -> int | None:
        """The matrix version the session's fills came from last, None before
        its first loop resolved them."""
        pin = await self._storage.get_matrix_tenant_storage().read_pin(ctx.org_id, session_id)
        return None if pin is None else pin.matrix_version

    def credentials(self, providers: ModelProvidersInterface) -> CallCredentialsInterface:
        clients = self._clients
        return CallCredentialsByFundingImpl(
            CallCredentialsPlatformImpl(providers),
            self._storage.get_account_storage(),
            (lambda: None) if clients is None else clients,
        )

    def build(self, managers: Managers) -> MatrixManagers:
        """The matrix managers over the engine's, once; built again, the
        same. The operators' publish asks the prices the resolver asks, the
        one source the managers price every call by."""
        if self._built is not None:
            return self._built
        storage = self._storage
        prices = self._prices or ModelPricesFromPricingImpl(managers.pricing)
        self._built = MatrixManagers(
            matrix=MatrixManagerImpl(
                storage.get_matrix_storage(),
                storage.get_matrix_tenant_storage(),
                storage.get_account_storage(),
                storage.get_trust_storage(),
                self.options,
                self._clock,
            ),
            matrix_operator=MatrixOperatorManagerImpl(
                storage.get_matrix_storage(),
                prices,
                self.options,
                self._required,
                self._clock,
            ),
        )
        return self._built
