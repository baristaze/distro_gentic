import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.integrations.payments import PaymentProviderInterface
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.base import new_id, utcnow
from acme.om.billing.manager import BillingManagerInterface
from acme.om.billing.rules import (
    anomaly_park,
    bucket_key,
    funding_of,
    line_keys,
    tally_of,
    window_of,
)
from acme.om.billing.storage import AccountStorageInterface, MoneyLedgerStorageInterface
from acme.om.billing.types.account import (
    MAX_ZONES,
    Account,
    AccountRequest,
    FundingMode,
    ZoneChange,
)
from acme.om.billing.types.ledger import (
    BUCKET_ORDER,
    Approval,
    Count,
    Credit,
    EntryKind,
    EntryPage,
    Grant,
    WindowRaise,
)
from acme.om.billing.types.plan import PlanCatalog, UnitScale
from acme.om.budgets import BudgetsManagerInterface
from acme.om.budgets.rules import window_bounds
from acme.om.budgets.types.amount import Amount
from acme.om.budgets.types.hold import HoldLine, Tally
from acme.om.context import OperatorContext, OperatorPermission, Permission, TenantContext
from acme.om.exceptions import NotAuthorized, NotFound, TenantMismatch, ValidationFailed
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.steps.types.header import ParkReason
from acme.om.tenancy.rules import check_time_zone

log = logging.getLogger(__name__)

OPENED = "billing.account.created"
UPDATED = "billing.account.updated"

SETS_BILLING = Permission.MANAGE_MEMBERS
"""An account governs what the org's members may spend, so opening or
changing one takes the permission that governs members, as a budget does."""

MAX_ENTRIES = 200
"""The entries one read of a tenant's ledger holds at most."""


class BillingManagerImpl(BillingManagerInterface):
    def __init__(
        self,
        accounts: AccountStorageInterface,
        ledger: MoneyLedgerStorageInterface,
        budgets: BudgetsManagerInterface,
        sessions: AgentSessionsManagerInterface,
        payments: PaymentProviderInterface,
        relay: OutboxRelayInterface,
        plans: PlanCatalog,
        units: UnitScale,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._accounts = accounts
        self._ledger = ledger
        self._budgets = budgets
        self._sessions = sessions
        self._payments = payments
        self._relay = relay
        self._plans = plans
        self._units = units
        self._clock = clock

    async def open_account(self, ctx: TenantContext, request: AccountRequest) -> Account:
        ctx.require(SETS_BILLING)
        plan = self._plans.latest(request.plan_id)
        if plan is None:
            raise ValidationFailed(f"there is no plan {request.plan_id}")
        if (request.funding is FundingMode.OWN_KEY) != (request.key_ref is not None):
            raise ValidationFailed("an own key is named by its reference, and only an own key is")
        try:
            check_time_zone(request.zone)
        except ValueError as refused:
            raise ValidationFailed(str(refused)) from None
        now = self._clock()
        account = Account(
            id=ctx.org_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            funding=request.funding,
            key_ref=request.key_ref,
            plan_id=plan.id,
            plan_version=plan.version,
            period_anchor=now,
            zones=(ZoneChange(zone=request.zone, at=now),),
        )
        rows = (versioned_row(ctx, OPENED, account.id, account.version),)
        if not await self._accounts.create_account(ctx.org_id, account, rows):
            # Opened already: the account as stored.
            return await self._read(ctx.org_id)
        await self._relay_all(ctx, rows)
        return account

    async def get_account(self, ctx: TenantContext) -> Account:
        ctx.require(Permission.READ)
        return await self._read(ctx.org_id)

    async def set_time_zone(self, ctx: TenantContext, zone: str, expected_version: int) -> Account:
        ctx.require(SETS_BILLING)
        try:
            check_time_zone(zone)
        except ValueError as refused:
            raise ValidationFailed(str(refused)) from None
        stored = await self._read(ctx.org_id)
        now = self._clock()
        # The oldest change goes once the list is full: by then it places no
        # window still open.
        zones = (*stored.zones, ZoneChange(zone=zone, at=now))[-MAX_ZONES:]
        changed = stored.model_copy(
            update={
                "zones": zones,
                "version": expected_version + 1,
                "updated_at": now,
                "updated_by": ctx.user_id,
            }
        )
        rows: tuple[OutboxRow, ...] = (versioned_row(ctx, UPDATED, changed.id, changed.version),)
        await self._accounts.write_account(ctx.org_id, changed, expected_version, rows)
        await self._relay_all(ctx, rows)
        return changed

    async def confirm_payment(
        self, ctx: TenantContext, payload: bytes, signature: str | None
    ) -> Credit:
        ctx.require(Permission.WRITE)
        now = self._clock()
        confirmation = self._payments.verify_confirmation(payload, signature, now)
        if confirmation.org_id != ctx.org_id:
            raise NotAuthorized("the payment confirms another tenant's credit")
        credit = await self._ledger.post_credit(
            ctx.org_id,
            Credit(
                id=new_id(),
                created_at=now,
                reference=confirmation.reference,
                amount_micros=confirmation.amount_micros,
                confirmed_at=confirmation.confirmed_at,
            ),
        )
        # Credit is room in a bucket, never a limit: the sessions parked on
        # the budget ask their gates again, and a limit still binds.
        await self._sessions.wake_parked(ctx, ParkReason.BUDGET)
        return credit

    async def grant_units(
        self, ctx: OperatorContext, org_id: UUID, units: int, reason: str
    ) -> Grant:
        ctx.require(OperatorPermission.WRITE)
        grant = Grant(
            id=new_id(),
            created_at=self._clock(),
            units=units,
            reason=reason,
            granted_by=ctx.identity_id,
        )
        return await self._ledger.post_grant(org_id, grant)

    async def get_entries(
        self,
        ctx: OperatorContext,
        org_id: UUID,
        *,
        kind: EntryKind | None = None,
        hold_id: UUID | None = None,
        session_id: UUID | None = None,
        limit: int,
    ) -> EntryPage:
        ctx.require(OperatorPermission.READ)
        bounded = max(1, min(limit, MAX_ENTRIES))
        # One more than the page: it says whether the read was cut, and stays out.
        entries = await self._ledger.read_entries(
            org_id, kind=kind, hold_id=hold_id, session_id=session_id, limit=bounded + 1
        )
        log.info("operator %s read the ledger of org %s", ctx.identity_id, org_id)
        return EntryPage(items=tuple(entries[:bounded]), has_more=len(entries) > bounded)

    async def raise_once(self, ctx: TenantContext, budget_id: UUID, amount: Amount) -> WindowRaise:
        ctx.require(SETS_BILLING)
        budget = await self._budgets.get_budget(ctx, budget_id)
        account = await self._read(ctx.org_id)
        now = self._clock()
        start, _ = window_of(budget.window, account, now)
        raised = await self._ledger.post_raise(
            ctx.org_id,
            WindowRaise(
                id=new_id(),
                created_at=now,
                budget_id=budget.id,
                window_start=start,
                cost_micros=amount.cost_micros or 0,
                tokens=amount.tokens or 0,
                raised_by=ctx.user_id,
            ),
        )
        await self._sessions.wake_parked(ctx, ParkReason.BUDGET)
        return raised

    async def approve_call(
        self, ctx: TenantContext, session_id: UUID, up_to_micros: int
    ) -> Approval:
        ctx.require(SETS_BILLING)
        session = await self._sessions.get_session(ctx, session_id)
        approval = await self._ledger.post_approval(
            ctx.org_id,
            Approval(
                id=new_id(),
                created_at=self._clock(),
                session_id=session.id,
                up_to_micros=up_to_micros,
                approved_by=ctx.user_id,
            ),
        )
        await self._sessions.wake_session(ctx, session.id, anomaly_park())
        return approval

    async def get_spend(self, ctx: TenantContext, budget_id: UUID) -> Tally:
        ctx.require(Permission.READ)
        budget = await self._budgets.get_budget(ctx, budget_id)
        account = await self._accounts.read_account(ctx.org_id)
        if account is None:
            # No call is held before an account is opened: its windows are
            # the engine's, in UTC, and they hold nothing.
            start, resets_at = window_bounds(budget.window, self._clock())
        elif account.id != ctx.org_id:
            raise TenantMismatch(f"account {account.id} is not {ctx.org_id}'s")
        else:
            start, resets_at = window_of(budget.window, account, self._clock())
        line = HoldLine(
            budget_id=budget.id,
            scope=budget.scope,
            window_start=start,
            resets_at=resets_at,
            amount=budget.amount,
        )
        counts = await self._ledger.read_counts(ctx.org_id, line_keys(line))
        return tally_of(line, counts)

    async def get_balances(self, ctx: TenantContext) -> tuple[Count, ...]:
        ctx.require(Permission.READ)
        account = await self._read(ctx.org_id)
        funding = funding_of(account, self._plans, self._units, self._clock())
        keys = [bucket_key(bucket, funding) for bucket in BUCKET_ORDER]
        counts = await self._ledger.read_counts(ctx.org_id, keys)
        return tuple(counts.get(key) or Count(counter=key[0], start=key[1]) for key in keys)

    async def _read(self, org_id: UUID) -> Account:
        account = await self._accounts.read_account(org_id)
        if account is None:
            raise NotFound(f"org {org_id} has no billing account")
        if account.id != org_id:
            raise TenantMismatch(f"account {account.id} is not {org_id}'s")
        return account

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        await self._relay.relay_all(ctx.org_id, rows)
