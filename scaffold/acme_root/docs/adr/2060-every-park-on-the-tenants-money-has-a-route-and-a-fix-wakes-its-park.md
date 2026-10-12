# ADR 2060: Every park on the tenant's money has a route, and a fix wakes its park

**Status**: accepted (2026-10-12)

## Context

The engine gives every park a person clears a route that clears it and
wakes the session. The platform's parks on money had none. Billing
approves a call far above its session's norm, raises a budget for one
window, credits a payment the provider confirmed, and grants units, but
only in `om/billing`. A session parked on one of them waited for a
generic unlock or a cancel. A grant woke nothing.

A park on a key the tenant holds none of waits with no clock, and saving
a key did not wake it. Nobody was told of it. Its notice, like every
provider park's, said the session tries again on its own.

A park on a price waited for an unlock. A price arrives with a release
of the price table, and nothing tells a parked session that it came.

## Decision

**A route for each billing park.** A person who approves calls past
their norm posts the session's cost approval
(`POST /v1/agent-sessions/{id}/cost-approval`). A person who sets budgets
raises a budget for the window open now (`POST /v1/budgets/{id}/raises`).
A person who may write posts a payment the provider confirmed
(`POST /v1/billing/payments`). An operator who may write grants units
(`POST /v1/admin/orgs/{org_id}/grants`). Each takes the permission
billing checks, wakes the sessions parked on it, and answers the ledger
entry it posted.

**A write of money posts once.** An approval, a raise, and a grant take
an Idempotency-Key, and the entry's id is the key's, so a retry after a
lost answer posts nothing more. A payment credits once by the provider's
own reference.

**A payment is posted by the tenant.** Billing refuses a confirmation of
another tenant, so the caller is a tenant's person, never the provider
on a route of its own. The body is the provider's confirmation, byte for
byte, and `Payment-Signature` its signature, checked before anything is
credited. A process wires its payment provider; one with none refuses
every payment.

**A grant wakes the tenant's funds.** Units are room in a bucket, as a
credit is. The grant runs under the tenant's own context, minted for the
org it names, so an org that is gone is refused before anything is
granted.

**A saved key wakes what waits for it.** Saving a key to a provider wakes
the sessions parked because the org held no key to it, or because the
provider refused the one it held. A permission the key lacks and the
account's billing are fixed at the provider, and their parks try again
by themselves.

**A missing key tells who saves keys.** It is the one provider park with
no clock, so it notifies the members who manage the org, with the route
that saves the key. A park the platform's operator fixes tells nobody in
the tenant.

**A price park tries again.** It tries again every five minutes, and its
cause says an operator prices the model. A limit that refused a call for
want of a price parks the same way: a raise clears none of it.

**A provider park is told by its cause.** A park on a key or an account
names who acts, an admin of the org or an operator. It is never told as
the provider's pace.

**Nothing is migrated.**

## Consequences

- No park on the tenant's money waits for a cancel alone.
- A park on a price costs a run up to the gate every five minutes, and
  no provider call.
- A person who approves a call past its norm names a cost, and the next
  call over it parks again.
- A deployment confirms no payment until a payment provider is wired.
