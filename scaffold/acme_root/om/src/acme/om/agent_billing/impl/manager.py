import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from acme.integrations.payments import PaymentProviderInterface
from acme.om.agent_billing.manager import AgentBillingManagerInterface
from acme.om.agent_billing.rules import (
    FUNDS_UNLOCK,
    anomaly_park,
    bucket_key,
    funding_of,
    line_keys,
    tally_of,
    window_of,
)
from acme.om.agent_billing.storage import SpendAccountStorageInterface, SpendLedgerStorageInterface
from acme.om.agent_billing.types.spend_account import (
    MAX_ZONES,
    FundingMode,
    SpendAccount,
    SpendAccountRequest,
    ZoneChange,
)
from acme.om.agent_billing.types.spend_ledger import (
    BUCKET_ORDER,
    Approval,
    Count,
    Credit,
    EntryKind,
    EntryPage,
    Grant,
    WindowRaise,
)
from acme.om.agent_billing.types.unit_plan import SpendUnitScale, UnitPlanCatalog
from acme.om.agent_sessions import AgentSessionsManagerInterface
from acme.om.agent_steps.types.header import ParkReason
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.context import OperatorContext, OperatorPermission, Permission, TenantContext
from acme.om.exceptions import (
    InvalidCredential,
    NotAuthorized,
    NotFound,
    TenantMismatch,
    ValidationFailed,
)
from acme.om.outbox import OutboxRelayInterface
from acme.om.outbox.types.row import OutboxRow, versioned_row
from acme.om.spend_budgets import SpendBudgetsManagerInterface
from acme.om.spend_budgets.rules import window_bounds
from acme.om.spend_budgets.types.amount import Amount
from acme.om.spend_budgets.types.spend_hold import SpendHoldLine, SpendTally
from acme.om.tenancy import TenancyManagerInterface
from acme.om.tenancy.rules import check_time_zone

log = logging.getLogger(__name__)

OPENED = "agent_billing.spend_account.created"
UPDATED = "agent_billing.spend_account.updated"

SETS_AGENT_BILLING = Permission.MANAGE_MEMBERS
"""A spend account governs what the org's members may spend, so opening or
changing one takes the permission that governs members, as a budget does."""

MAX_ENTRIES = 200
"""The entries one read of a tenant's ledger holds at most."""


class AgentBillingManagerImpl(AgentBillingManagerInterface):
    def __init__(
        self,
        spend_accounts: SpendAccountStorageInterface,
        ledger: SpendLedgerStorageInterface,
        budgets: SpendBudgetsManagerInterface,
        sessions: AgentSessionsManagerInterface,
        tenancy: TenancyManagerInterface,
        payments: PaymentProviderInterface,
        relay: OutboxRelayInterface,
        unit_plans: UnitPlanCatalog,
        spend_units: SpendUnitScale,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._spend_accounts = spend_accounts
        self._ledger = ledger
        self._budgets = budgets
        self._sessions = sessions
        self._tenancy = tenancy
        self._payments = payments
        self._relay = relay
        self._unit_plans = unit_plans
        self._spend_units = spend_units
        self._clock = clock

    async def open_spend_account(
        self, ctx: TenantContext, request: SpendAccountRequest
    ) -> SpendAccount:
        ctx.require(SETS_AGENT_BILLING)
        unit_plan = self._unit_plans.latest(request.unit_plan_id)
        if unit_plan is None:
            raise ValidationFailed(f"there is no unit plan {request.unit_plan_id}")
        if (request.funding is FundingMode.OWN_KEY) != (request.key_ref is not None):
            raise ValidationFailed("an own key is named by its reference, and only an own key is")
        try:
            check_time_zone(request.zone)
        except ValueError as refused:
            raise ValidationFailed(str(refused)) from None
        now = self._clock()
        spend_account = SpendAccount(
            id=ctx.org_id,
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            funding=request.funding,
            key_ref=request.key_ref,
            unit_plan_id=unit_plan.id,
            unit_plan_version=unit_plan.version,
            period_anchor=now,
            zones=(ZoneChange(zone=request.zone, at=now),),
        )
        rows = (versioned_row(ctx, OPENED, spend_account.id, spend_account.version),)
        if not await self._spend_accounts.create_spend_account(ctx.org_id, spend_account, rows):
            # Opened already: the spend account as stored.
            return await self._read(ctx.org_id)
        await self._relay_all(ctx, rows)
        return spend_account

    async def get_spend_account(self, ctx: TenantContext) -> SpendAccount:
        ctx.require(Permission.READ)
        return await self._read(ctx.org_id)

    async def set_time_zone(
        self, ctx: TenantContext, zone: str, expected_version: int
    ) -> SpendAccount:
        ctx.require(SETS_AGENT_BILLING)
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
        await self._spend_accounts.write_spend_account(ctx.org_id, changed, expected_version, rows)
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
        # The tenant's own context, the one its sessions are woken under: the
        # credit is room for every session of the org, those the payer does
        # not see among them, and the payer stays its attribution.
        tenant = await self._tenancy.service_context(ctx, ctx.org_id, ctx.user_id)
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
        await self._sessions.wake_parked(tenant, ParkReason.BUDGET)
        return credit

    async def grant_units(
        self,
        ctx: OperatorContext,
        org_id: UUID,
        units: int,
        reason: str,
        *,
        grant_id: UUID | None = None,
    ) -> Grant:
        ctx.require(OperatorPermission.WRITE)
        # The tenant's own context, the one its sessions are woken under: an
        # org that is gone has none, and is granted nothing.
        try:
            tenant = await self._tenancy.service_context(ctx, org_id, EMPTY_UUID)
        except InvalidCredential:
            raise NotFound(f"org {org_id} not found") from None
        grant = Grant(
            id=grant_id or new_id(),
            created_at=self._clock(),
            units=units,
            reason=reason,
            granted_by=ctx.identity_id,
        )
        granted = await self._ledger.post_grant(org_id, grant)
        log.info("operator %s granted org %s %d units", ctx.identity_id, org_id, granted.units)
        # Granted units are room in a bucket, never a limit: the sessions
        # parked on the funds ask their gates again.
        await self._sessions.wake_parked(tenant, ParkReason.BUDGET, FUNDS_UNLOCK)
        return granted

    async def get_entries(
        self,
        ctx: OperatorContext,
        org_id: UUID,
        *,
        kind: EntryKind | None = None,
        spend_hold_id: UUID | None = None,
        agent_session_id: UUID | None = None,
        limit: int,
    ) -> EntryPage:
        ctx.require(OperatorPermission.READ)
        bounded = max(1, min(limit, MAX_ENTRIES))
        # One more than the page: it says whether the read was cut, and stays out.
        entries = await self._ledger.read_entries(
            org_id,
            kind=kind,
            spend_hold_id=spend_hold_id,
            agent_session_id=agent_session_id,
            limit=bounded + 1,
        )
        log.info("operator %s read the ledger of org %s", ctx.identity_id, org_id)
        return EntryPage(items=tuple(entries[:bounded]), has_more=len(entries) > bounded)

    async def raise_once(
        self,
        ctx: TenantContext,
        spend_budget_id: UUID,
        amount: Amount,
        *,
        raise_id: UUID | None = None,
    ) -> WindowRaise:
        ctx.require(SETS_AGENT_BILLING)
        budget = await self._budgets.get_spend_budget(ctx, spend_budget_id)
        spend_account = await self._read(ctx.org_id)
        now = self._clock()
        start, _ = window_of(budget.window, spend_account, now)
        raised = await self._ledger.post_raise(
            ctx.org_id,
            WindowRaise(
                id=raise_id or new_id(),
                created_at=now,
                spend_budget_id=budget.id,
                window_start=start,
                cost_micros=amount.cost_micros or 0,
                tokens=amount.tokens or 0,
                raised_by=ctx.user_id,
            ),
        )
        await self._sessions.wake_parked(ctx, ParkReason.BUDGET)
        return raised

    async def approve_call(
        self,
        ctx: TenantContext,
        agent_session_id: UUID,
        up_to_micros: int,
        *,
        approval_id: UUID | None = None,
    ) -> Approval:
        ctx.require(SETS_AGENT_BILLING)
        session = await self._sessions.get_agent_session(ctx, agent_session_id)
        approval = await self._ledger.post_approval(
            ctx.org_id,
            Approval(
                id=approval_id or new_id(),
                created_at=self._clock(),
                agent_session_id=session.id,
                up_to_micros=up_to_micros,
                approved_by=ctx.user_id,
            ),
        )
        await self._sessions.wake_agent_session(ctx, session.id, anomaly_park())
        return approval

    async def get_spend(self, ctx: TenantContext, spend_budget_id: UUID) -> SpendTally:
        ctx.require(Permission.READ)
        budget = await self._budgets.get_spend_budget(ctx, spend_budget_id)
        spend_account = await self._spend_accounts.read_spend_account(ctx.org_id)
        if spend_account is None:
            # No call is held before a spend account is opened: its windows are
            # the engine's, in UTC, and they hold nothing.
            start, resets_at = window_bounds(budget.window, self._clock())
        elif spend_account.id != ctx.org_id:
            raise TenantMismatch(f"spend account {spend_account.id} is not {ctx.org_id}'s")
        else:
            start, resets_at = window_of(budget.window, spend_account, self._clock())
        line = SpendHoldLine(
            spend_budget_id=budget.id,
            scope=budget.scope,
            window_start=start,
            resets_at=resets_at,
            amount=budget.amount,
        )
        counts = await self._ledger.read_counts(ctx.org_id, line_keys(line))
        return tally_of(line, counts)

    async def get_balances(self, ctx: TenantContext) -> tuple[Count, ...]:
        ctx.require(Permission.READ)
        spend_account = await self._read(ctx.org_id)
        funding = funding_of(spend_account, self._unit_plans, self._spend_units, self._clock())
        keys = [bucket_key(bucket, funding) for bucket in BUCKET_ORDER]
        counts = await self._ledger.read_counts(ctx.org_id, keys)
        return tuple(counts.get(key) or Count(counter=key[0], start=key[1]) for key in keys)

    async def _read(self, org_id: UUID) -> SpendAccount:
        spend_account = await self._spend_accounts.read_spend_account(org_id)
        if spend_account is None:
            raise NotFound(f"org {org_id} has no spend account")
        if spend_account.id != org_id:
            raise TenantMismatch(f"spend account {spend_account.id} is not {org_id}'s")
        return spend_account

    async def _relay_all(self, ctx: TenantContext, rows: tuple[OutboxRow, ...]) -> None:
        """The write has committed; a relay that fails is left to the sweep."""
        await self._relay.relay_all(ctx.org_id, rows)
