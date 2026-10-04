# Billing

Who pays for what an agent spends, and the one ledger that records it.
The engine's gate holds a call before it starts; billing is what stands
behind that gate. This is one of the kinds of thing [Acme is made
of](../../../../README.md).

## What it holds

- **Account**: one per org. It says who pays the model provider (the
  platform's key, or the tenant's own key), the plan and its version,
  when the billing periods start, and the tenant's time zones in the
  order they were set.
- **Plan**: a versioned row of a catalog the platform publishes: the
  units each billing period includes, and the price of one unit. A plan
  changes by a new version, never in place.
- **Unit**: a token unit weighted by cost. One unit stands for a fixed
  slice of reference cost, so a plan can include usage across models
  without promising dollars or a token count. The platform publishes
  the scale.
- **Bucket**: what pays for a call on the platform's key, drawn in a
  fixed order: the plan's included units, granted units, prepaid
  credits, and a line of credit. Prepaid and postpaid differ only in
  which bucket has room.
- **Ledger**: one table of entries, each written once: every hold,
  settlement, and charge, every confirmed credit and granted unit,
  every one-time raise, and every approval a person gives. Beside it, a
  count per counter and period, which the entries move.
- **Price book**: the engine's price table, read by version. A call is
  held at the version in force and billed at that same version.

## What can happen

- **Open an account**, or change its time zone. Either takes the
  permission that governs the org's members.
- **Hold a call.** The gate asks who pays, holds the worst case on every
  limit in its window, and draws it on the buckets, all in one
  transaction of the ledger. Or it turns the call away, and nothing is
  written.
- **Settle a call.** The settlement and its charge are written together,
  once.
- **Confirm a payment.** The payment provider's signed confirmation
  posts a credit, once per payment.
- **Raise a limit once.** The raise counts in the window open now and in
  no other.
- **Approve a call** that the anomaly guard parked.
- **Read a tenant's ledger.** An operator reads its entries, the newest
  first, naming the tenant, under the operators' read.
- **Settle what nobody settled.** A hold an hour past due with no
  settlement belongs to a run that died. A model call's hold falls due at
  its opening, and a job's at its deadline, which it lives to. The sweep
  settles it through its gate, at the bill the provider gives, else
  whole, and releases it only on the provider's proof (`sweep.py`).
- **Purge a deleted tenant.** Its account goes with its other rows. Its
  ledger is counted and never deleted, so the sweep never marks the
  tenant purged while an entry remains (`purge.py`).

## The rules

- **One ledger, one price source.** Every hold, settlement, and charge is
  an entry of the one ledger. A cap and a bill read the same row of the
  same versioned table.
- **Nothing is spent when nobody can say who pays.** A missing account,
  an own key with no reference, a plan the catalog lacks, or a stored
  account this process cannot read refuses the call. Nothing falls back
  to the platform's key. An account on its own key is held only for a
  call that carries one of the tenant's keys, and an account the
  platform pays only for a call that does not.
- **A change of time zone never makes budget.** Days and weeks follow
  the tenant's zone, months its billing period. A change keeps the open
  window's start and ends it at the new zone's first boundary at or
  after its old end.
- **A credit counts only once confirmed.** Its signature must check out,
  and a top-up never raises a limit.
- **A rate limit is not a spend limit.** A spend limit, or funds no
  bucket covers, parks the session on its budget. The provider's pace
  parks it on the provider. Each is told in its own words.
- **A call far above its session's norm waits for a person**, and the
  operator is paged. The norm is the session's model calls'. A job that
  spends is judged by its declared rate and its budgets: it neither meets
  the norm nor counts in it.
- **What the ledger holds is written once.** No serving login rewrites
  or removes an entry.

## How another namespace composes it

A root wires `impl/gate.py`'s `MoneyCallGateImpl` as the call gate the
windows and the loop read, over `MoneyGateImpl` as the budget gate. The
gate reads the engine's budgets through their storage, and parks a call
through the engine's `GateParked`, which the loop parks on. The payment
provider is in `integrations/payments/`.
