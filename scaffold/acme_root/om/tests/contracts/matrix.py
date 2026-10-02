"""The platform's loop with the model matrix as its resolver: the loop
suites' memory storage, scripted providers, and fake clock, behind the
platform's money, with the trust swimlane's keys, and a scripted client
built on each key a tenant saves. What the matrix suites share: the fills,
an operator, and a matrix a case stages, qualifies, and publishes in one
call."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from acme.infra.impl.local import InfraLocalImpl
from acme.integrations.model_providers import ModelProviderInterface
from acme.integrations.model_providers.scripted import ModelProviderScriptedImpl
from acme.integrations.model_providers.types import Effort, ProviderName
from acme.om.agents.impl.loop import LoopOptions
from acme.om.base import new_id
from acme.om.billing.types.account import FundingMode
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    TenantContext,
)
from acme.om.matrix.impl.resolver import MatrixOptions, Workload
from acme.om.matrix.root import MatrixLayer, MatrixManagers
from acme.om.matrix.types.matrix import MatrixKey, MatrixRow, MatrixVersion
from acme.om.matrix.types.record import BenchmarkRun
from acme.om.models.types.fill import MAIN, SUMMARIZER, Eligibility, Fill, ModelRole
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.root import StorageInterface
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.trust.impl.keys import KeyProbeTwinImpl
from acme.om.trust.impl.placement import PlacementCloudImpl
from acme.om.trust.root import TrustLayer, TrustManagers
from acme.om.trust.types.identities import Executor, ExecutorKind
from contracts.loops import Loop
from contracts.money import Money, money_over

SONNET = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-sonnet-5-5",
    effort=Effort.HIGH,
    max_output_tokens=32_000,
    context_window=1_000_000,
)
OPUS = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-opus-5-5",
    effort=Effort.HIGH,
    max_output_tokens=32_000,
    context_window=1_000_000,
)
HAIKU = Fill(
    provider=ProviderName.ANTHROPIC,
    model="claude-haiku-4-5",
    max_output_tokens=8_000,
    context_window=200_000,
)
SOL = Fill(
    provider=ProviderName.OPENAI,
    model="gpt-6.1-sol",
    effort=Effort.HIGH,
    max_output_tokens=32_000,
    context_window=1_050_000,
)
LUNA = Fill(
    provider=ProviderName.OPENAI,
    model="gpt-6-luna",
    effort=Effort.LOW,
    max_output_tokens=8_000,
    context_window=1_050_000,
)
UNPRICED = SONNET.model_copy(update={"model": "a-model-the-list-does-not-hold"})

EU = Eligibility(zero_retention=True, region="eu-central-1")
"""What a tenant that keeps nothing and stays in one region requires."""


def kept_in(fill: Fill, eligibility: Eligibility) -> Fill:
    """The same model, offered with `eligibility`."""
    return fill.model_copy(update={"eligibility": eligibility})


CATCH_ALL = (
    MatrixRow(key=MatrixKey(role=MAIN), fills=(SONNET, SOL)),
    MatrixRow(key=MatrixKey(role=SUMMARIZER), fills=(HAIKU, LUNA)),
    MatrixRow(fills=(SONNET,)),
)
"""A matrix that answers every question: the engine's own two roles, each
with a fallback, and the row that matches everything."""


def operator() -> OperatorContext:
    return OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="root@example.test",
        credential_kind=CredentialKind.LOGIN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.WRITE),
    )


@dataclass
class Fleet:
    money: Money
    trust: TrustManagers
    matrix: MatrixManagers
    layer: MatrixLayer
    admin: OperatorContext
    probe: KeyProbeTwinImpl
    trust_infra: InfraLocalImpl
    """The infra the trust swimlane keeps a tenant's key values in."""
    keyed: dict[str, ModelProviderScriptedImpl] = field(
        default_factory=dict[str, ModelProviderScriptedImpl]
    )
    """Each client built on a tenant's key, by the key's value."""

    def on_key(self, value: str, provider: ProviderName) -> ModelProviderScriptedImpl:
        """The scripted client a call on the tenant's key `value` reaches."""
        return self.keyed.setdefault(value, ModelProviderScriptedImpl(provider))

    @property
    def loop(self) -> Loop:
        return self.money.loop

    @property
    def owner(self) -> TenantContext:
        return self.money.loop.owner

    async def qualify(self, fill: Fill, *roles: ModelRole, passed: bool = True) -> None:
        """A benchmark run of the fill's model for each role, recorded."""
        for role in roles:
            run = BenchmarkRun(
                provider=fill.provider,
                model=fill.model,
                role=role,
                benchmark="swe-lite",
                passed=passed,
                run=f"run-{new_id().hex[:8]}",
            )
            await self.matrix.matrix_operator.record_benchmark(self.admin, run)

    async def publish(
        self,
        rows: Sequence[MatrixRow] = CATCH_ALL,
        roles: Sequence[ModelRole] = (MAIN, SUMMARIZER),
    ) -> MatrixVersion:
        """The rows staged as a version, every fill qualified for every role
        its row serves, and the version published."""
        operators = self.matrix.matrix_operator
        version = await operators.stage(self.admin, roles, rows)
        for row in version.rows:
            for fill in row.fills:
                await self.qualify(fill, *version.roles_of(row))
        return await operators.publish(self.admin, version.number)


async def fleet_over(
    tmp_path: Path,
    *,
    options: MatrixOptions | None = None,
    funding: FundingMode = FundingMode.PLATFORM,
    workload: Workload | None = None,
    loop_options: LoopOptions | None = None,
    storage: StorageInterface | None = None,
    owner: TenantContext | None = None,
) -> Fleet:
    """`storage` None is the memory storage, and `owner` None a fresh
    tenant's owner, whose account opens on `funding`; a suite over Postgres
    hands in both."""
    storage = storage or StorageMemoryImpl()
    keyed: dict[str, ModelProviderScriptedImpl] = {}

    def client(provider: ProviderName, value: str) -> ModelProviderInterface:
        return keyed.setdefault(value, ModelProviderScriptedImpl(provider))

    runner = Executor(kind=ExecutorKind.CLOUD, credential_id=new_id(), label="session-runner-1")
    probe = KeyProbeTwinImpl()
    trust_infra = InfraLocalImpl(tmp_path / "trust")
    trust = TrustLayer(
        storage,
        trust_infra,
        placement=PlacementCloudImpl(runner),
        probe=probe,
        clients=client,
    )
    layer = MatrixLayer(
        storage,
        options=options,
        clients=lambda: trust.managers.provider_clients,
        workload=workload,
    )
    money = money_over(
        tmp_path,
        storage=storage,
        owner=owner,
        loop_options=loop_options,
        models_layer=layer.layer,
        tools_layer=trust.tools,
    )
    trusted = trust.build(money.loop.managers)
    built = layer.build(money.loop.managers)
    await money.open(
        funding=funding, key_ref=None if funding is FundingMode.PLATFORM else "own-keys"
    )
    return Fleet(money, trusted, built, layer, operator(), probe, trust_infra, keyed)
