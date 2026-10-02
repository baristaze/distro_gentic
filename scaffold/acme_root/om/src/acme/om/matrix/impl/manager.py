import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from acme.om.base import new_id, utcnow
from acme.om.billing.storage import AccountStorageInterface
from acme.om.billing.types.account import FundingMode
from acme.om.context import OperatorContext, OperatorPermission, Permission, TenantContext
from acme.om.exceptions import NotFound, PreconditionFailed, ValidationFailed
from acme.om.matrix import rules
from acme.om.matrix.impl.resolver import MatrixOptions
from acme.om.matrix.manager import MatrixManagerInterface, MatrixOperatorManagerInterface
from acme.om.matrix.storage import MatrixStorageInterface, MatrixTenantStorageInterface
from acme.om.matrix.types.matrix import MatrixRow, MatrixStatus, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, BenchmarkRun, ModelRef, Retirement
from acme.om.matrix.types.tenant import FillOverride, MatrixPin
from acme.om.models.prices import ModelPricesInterface
from acme.om.models.types.fill import Fill, ModelRole
from acme.om.trust.storage import TrustStorageInterface

log = logging.getLogger(__name__)


class MatrixOperatorManagerImpl(MatrixOperatorManagerInterface):
    """The operators' plane of the matrix: global rows, written under no
    tenant, each by an operator who holds the plane's write."""

    def __init__(
        self,
        matrix: MatrixStorageInterface,
        prices: ModelPricesInterface,
        options: MatrixOptions,
        required: frozenset[ModelRole],
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        """`required` is every model role a version must serve: those the
        engine calls and those of each kind the platform runs."""
        self._matrix = matrix
        self._prices = prices
        self._options = options
        self._required = required
        self._clock = clock

    async def stage(
        self, admin: OperatorContext, roles: Sequence[ModelRole], rows: Sequence[MatrixRow]
    ) -> MatrixVersion:
        admin.require(OperatorPermission.WRITE)
        last = await self._matrix.read_latest(None)
        try:
            version = MatrixVersion(
                id=new_id(),
                number=1 if last is None else last.number + 1,
                roles=tuple(roles),
                rows=tuple(rows),
                created_at=self._clock(),
                created_by=admin.identity_id,
            )
        except ValidationError as error:
            raise ValidationFailed(f"matrix version: {error}"[:500]) from None
        await self._matrix.create_version(version)
        log.info("operator %s staged matrix version %d", admin.identity_id, version.number)
        return version

    async def publish(self, admin: OperatorContext, number: int) -> MatrixVersion:
        admin.require(OperatorPermission.WRITE)
        version = await self._matrix.read_version(number)
        if version is None:
            raise NotFound(f"matrix version {number} not found")
        if version.status is not MatrixStatus.PENDING:
            raise PreconditionFailed(f"matrix version {number} is published already")
        models = sorted(
            frozenset(ModelRef.of(fill) for row in version.rows for fill in row.fills),
            key=lambda model: model.name,
        )
        results = [
            result
            for model in models
            for result in await self._matrix.read_results(model, self._options.reads)
        ]
        latest = rules.latest_results(results)
        retired = frozenset(r.ref for r in await self._matrix.read_retirements(self._options.reads))

        def qualified(model: ModelRef, role: ModelRole) -> bool:
            found = latest.get((model, role))
            return found is not None and found.passed

        refusals = rules.publish_refusals(
            version,
            priced=lambda model: self._prices.priced(model.provider, model.model),
            qualified=qualified,
            retired=lambda model: model in retired,
            required=self._required,
        )
        if refusals:
            raise ValidationFailed(
                f"matrix version {number} is not published: {'; '.join(refusals)}"[:2000]
            )
        published = await self._matrix.publish_version(number, self._clock(), admin.identity_id)
        if published is None:
            raise PreconditionFailed(
                f"matrix version {number} is no longer pending, or a later one is published"
            )
        log.info("operator %s published matrix version %d", admin.identity_id, number)
        return published

    async def get_version(self, admin: OperatorContext, number: int | None) -> MatrixVersion:
        admin.require(OperatorPermission.READ)
        found = (
            await self._matrix.read_latest(MatrixStatus.PUBLISHED)
            if number is None
            else await self._matrix.read_version(number)
        )
        if found is None:
            raise NotFound("no such version of the matrix")
        return found

    async def record_benchmark(self, admin: OperatorContext, run: BenchmarkRun) -> BenchmarkResult:
        admin.require(OperatorPermission.WRITE)
        result = BenchmarkResult(
            id=new_id(),
            created_at=self._clock(),
            recorded_by=admin.identity_id,
            **run.model_dump(),
        )
        await self._matrix.add_result(result)
        log.info(
            "operator %s recorded %s of %s for %s: %s",
            admin.identity_id,
            run.benchmark,
            run.ref.name,
            run.role,
            "passed" if run.passed else "failed",
        )
        return result

    async def retire_model(self, admin: OperatorContext, model: ModelRef) -> Retirement:
        admin.require(OperatorPermission.WRITE)
        retirement = Retirement(
            id=new_id(),
            created_at=self._clock(),
            provider=model.provider,
            model=model.model,
            recorded_by=admin.identity_id,
        )
        stored = await self._matrix.add_retirement(retirement)
        log.info("operator %s retired %s", admin.identity_id, model.name)
        return stored


class MatrixManagerImpl(MatrixManagerInterface):
    """What a tenant reads and chooses of the matrix."""

    def __init__(
        self,
        matrix: MatrixStorageInterface,
        tenants: MatrixTenantStorageInterface,
        accounts: AccountStorageInterface,
        keys: TrustStorageInterface,
        options: MatrixOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._matrix = matrix
        self._tenants = tenants
        self._accounts = accounts
        self._keys = keys
        self._options = options
        self._clock = clock

    async def get_pin(self, ctx: TenantContext, session_id: UUID) -> MatrixPin:
        ctx.require(Permission.READ)
        pin = await self._tenants.read_pin(ctx.org_id, session_id)
        if pin is None:
            raise NotFound(f"session {session_id} holds no matrix version")
        return pin

    async def choose_fill(self, ctx: TenantContext, role: ModelRole, fill: Fill) -> FillOverride:
        ctx.require(Permission.MANAGE_MEMBERS)
        account = await self._accounts.read_account(ctx.org_id)
        if account is None or account.funding is not FundingMode.OWN_KEY:
            raise ValidationFailed("only a tenant that pays its providers on its own keys chooses")
        if await self._keys.read_live_key(ctx.org_id, fill.provider) is None:
            raise ValidationFailed(f"the tenant holds no live {fill.provider.value} key")
        current = await self._matrix.read_latest(MatrixStatus.PUBLISHED)
        if current is None or fill not in rules.serves(current, role):
            raise ValidationFailed(f"the matrix qualified {fill.name} for no model role {role}")
        now = self._clock()
        choice = FillOverride(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            role=role,
            fill=fill,
        )
        return await self._tenants.write_override(ctx.org_id, choice)

    async def drop_choice(self, ctx: TenantContext, role: ModelRole) -> bool:
        ctx.require(Permission.MANAGE_MEMBERS)
        return await self._tenants.delete_override(ctx.org_id, role)

    async def get_choices(self, ctx: TenantContext) -> tuple[FillOverride, ...]:
        ctx.require(Permission.READ)
        return tuple(await self._tenants.read_overrides(ctx.org_id, self._options.reads))
