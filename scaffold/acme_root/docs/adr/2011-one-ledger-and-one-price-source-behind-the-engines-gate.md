# ADR 2011: One ledger and one price source behind the engine's gate

**Status**: accepted (2026-10-03)

## Context

The engine gates every model call and every spending job before it
starts, and keeps its own ledger of holds and settlements (ADR 1006).
The platform adds what stands behind the gate: who pays, the buckets
that pay, the charge, limits counted in the tenant's time zone, and an
anomaly guard. Each of these posts or reads money, and two places that
count money drift apart. A cap read at one price and a bill read at
another is the same drift.

## Decision

**One ledger.** Billing keeps one table of entries in `activity`: every
hold, settlement, charge, confirmed credit, granted unit, one-time
raise, and approval. Each is written once; the serving logins keep
SELECT and INSERT on it and lose UPDATE and DELETE, as on the engine's
ledger. Beside it, one count per counter and period: a budget's cost or
tokens in a window, or a bucket in a billing period or for the
account's life. An entry moves its counts under their locks, taken in
one order, in the transaction that writes it. The counts can be rebuilt
from the entries.

**The hold carries the account.** The gate reads the account in `core`,
and the hold carries what it read: the funding mode, the plan, the
unit's scale, and the billing period. The ledger then draws the buckets
on the hold alone, so nothing crosses a role. A settlement and its
charge are written in one transaction, once per hold.

**One price source, by version.** The engine's list table is the one
source. Billing reads it through a price book that keeps every
published version. A model call's hold names the version, provider, and
model its cap was read from, and its usage is billed from that row,
after the next version is read and in another process too.

**A gate that parks.** Funds no bucket covers park the session on its
budget, naming the funds. A call far above its session's norm parks it
for a person and pages the operator. The engine's refusal names only
budgets, so the engine gains `GateParked`, an exception that carries
its own park, and the loop parks on it. The loop also parks for a
person on `SpenderUnknown`, as it does on `NoSpender`.

**Windows in the tenant's zone.** Days and weeks follow the tenant's
time zone, kept as the zones it set, in order; months follow the
billing period. A change of zone keeps the open window's start and ends
it at the new zone's first boundary at or after its old end, so a
window is never shorter than its kind and no change opens a second one.

## Consequences

- With billing's gate wired, the engine's own ledger tables stay empty,
  and the engine's `get_spend` reads windows in UTC. Billing's
  `get_spend` reads the same counts the gate checks, and is the view.
- A spend past its hold is charged in full to the last money bucket the
  account has, never absorbed.
- An entry's body is JSON, read by its kind; a kind this process does
  not know is a defect of the deploy, never read as another.
- The ledger grows with every call. Its retention is a decision of its
  own, made when a tenant's ledger is first purged.
