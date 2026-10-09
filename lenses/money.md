# Money

Group id: `money`. Covers Money and Models Are a Fleet Decision of
`distro_gentic_spec.md`.

This group judges everything behind the engine's budget gate: metering,
limits and their windows, units, charges, and billing, rate and spend
limits, outages and anomalies, the one ledger and the one price source,
and the model matrix. It leaves the gate itself, the hold, and usage to
the engine; the park a provider outage causes across the fleet and the
hold the sweep settles to `fleet`; and a tenant's provider key as a
secret to `wall`.

## MNY-01 One aggregation serves every view of usage

**Principle.** Metering collects the engine's usage records, one per
model call or spending job, and one aggregation serves every view of
them: a dashboard, a list, a cap.

**Source.** Money, Metering and Limits.

**Look for.** Where usage records are collected; every query that sums
them for a dashboard, a list, or a cap.

**Violation.** A model call or a spending job with no usage record, or
with two; a dashboard, a list, or a cap that sums usage its own way.

**Severity.** medium

**Check.** review

## MNY-02 A window follows the tenant's time zone and the billing period

**Principle.** Limits are budgets over a scope (person, project, team,
tenant) and a window (hour, day, week, month, or custom). Days and weeks
follow the tenant's time zone, months follow the billing period, and a
change of time zone never manufactures budget.

**Source.** Money, Metering and Limits.

**Look for.** The scopes and windows a limit can take; the window
arithmetic; what a change of time zone does to an open window.

**Violation.** Day or week windows in UTC or the server's zone; month
windows on calendar months when the billing period differs; a change of
time zone that opens a fresh window or resets a count.

**Severity.** medium

**Check.** review

## MNY-03 A limit counts settled spend and open holds

**Principle.** A limit counts settled spend plus open holds, and a
one-time raise applies to the current window only.

**Source.** Money, Metering and Limits.

**Look for.** What a limit's check sums; how a raise is stored, and when
it ends.

**Violation.** A limit that counts settled spend alone; a raise that
carries into later windows, or changes the limit itself.

**Severity.** high

**Check.** review

## MNY-04 A unit beside usage and cost, and a charge apart from both

**Principle.** Beside native usage and reference cost, the platform
defines an abstract unit: a token unit weighted by cost, so a plan can
include usage across models and providers without promising dollars or
a token count. The weights are the platform's to publish. The charge is
what a tenant is billed.

**Source.** Money, Units, Charges, and Billing.

**Look for.** The unit's definition, and where its weights come from;
the fields for usage, reference cost, units, and charge.

**Violation.** A plan that promises dollars or a token count; unit
weights a tenant or a session sets; one figure standing for two of
usage, reference cost, units, and charge.

**Severity.** medium

**Check.** review

## MNY-05 The ledger is append-only, and a hold draws in a fixed order

**Principle.** Billing keeps accounts, versioned plans, and an
append-only ledger. A hold draws on buckets in a fixed order: the plan's
included units, granted units, prepaid credits, and an enterprise line
of credit. Prepaid and postpaid differ in which bucket pays, never in
the path a call takes.

**Source.** Money, Units, Charges, and Billing.

**Look for.** The ledger's writes; the order a hold draws buckets in;
every branch on how a tenant pays.

**Violation.** A ledger row updated or deleted; a plan changed in place;
a hold that draws buckets in another order; a call path that branches on
prepaid or postpaid.

**Severity.** high

**Check.** review

## MNY-06 A credit counts once confirmed, and a top-up never raises a limit

**Principle.** Credits count only after the payment provider's signed
confirmation, and a top-up never raises a limit. No top-up relaxes a
rate limit either.

**Source.** Money, Units, Charges, and Billing; Rate Limits Are Not
Spend Limits.

**Look for.** When a bought credit becomes spendable; what a top-up
changes.

**Violation.** A credit posted on the client's word or on an unsigned
event; a top-up that raises a spend limit or relaxes a rate limit.

**Severity.** high

**Check.** review

## MNY-07 Rate and spend are different limits

**Principle.** A rate limit governs how fast; a spend limit governs how
much. A rate limit throttles, queues, or parks the session on the
provider. A spend limit parks the session on its budget. They are
evaluated apart, and neither is ever reported as the other.

**Source.** Money, Rate Limits Are Not Spend Limits.

**Look for.** Where each limit is evaluated; the park reason each
writes; what a person is told of each.

**Violation.** One check that stands for both; a rate limit that parks on
the budget, or a spend limit that parks on the provider; a message that
reports one as the other.

**Severity.** medium

**Check.** review

## MNY-08 The outage signal is shared, per provider and credential

**Principle.** The platform shares the guideline's outage signal across
its runners, one per provider and credential, in the shared cache. A
session that reads it parks on the provider, the engine's park, so it
meets a known outage in a second. An unreachable cache is a declared
degraded answer: calls proceed, and each session's own retries and its
park on the provider hold. A tenant on its own key has a signal of its
own, and a billing or credential error on that key parks only its
sessions.

**Source.** Money, Outages and Anomalies.

**Look for.** Where the outage signal lives and how it is keyed; what a
runner does when the cache is unreachable; how an error on a tenant's
key is scoped.

**Violation.** A signal kept per runner, or keyed by provider alone;
calls that stop or fail when the cache is unreachable; a billing or
credential error on a tenant's key that parks other tenants' sessions.

**Severity.** medium

**Check.** review

## MNY-09 An anomaly guard parks a call far above its session's norm

**Principle.** An anomaly guard parks a call for a person when its
expected cost is far above its session's norm, and pages the operator.

**Source.** Money, Outages and Anomalies.

**Look for.** The anomaly guard: what it compares, and what it does.

**Violation.** No anomaly guard before a call; a guard that refuses or
fails the call instead of parking it for a person; a guard that does not
page the operator.

**Severity.** medium

**Check.** review

## MNY-10 One ledger and one price source

**Principle.** Every hold, settlement, and charge posts to one ledger,
and a cap and a bill read the same price, from the same versioned table.

**Source.** Money, One Price Source.

**Look for.** Every write of a hold, a settlement, or a charge; every
price lookup, for a cap and for a bill.

**Violation.** A hold, a settlement, or a charge kept outside the
ledger; a cap and a bill priced from different tables or versions, or
from a price copied into code.

**Severity.** high

**Check.** review

## MNY-11 Spend fails closed

**Principle.** The platform fails closed for spend: when it cannot tell
who pays, nothing is spent, and an unreadable funding mode never falls
back to the platform's key.

**Source.** Money, One Price Source.

**Look for.** What happens when the payer or the funding mode cannot be
read.

**Violation.** A call made when the payer is unknown; an unreadable
funding mode that falls back to the platform's key.

**Severity.** high

**Check.** review

## MNY-12 The matrix answers every question

**Principle.** The platform answers which model serves which task with a
matrix: for each environment, model role, agent kind, plan tier, and
workload class, a fill. The most specific row wins, and a row that
matches everything is required, so every question has an answer.

**Source.** Models Are a Fleet Decision.

**Look for.** The matrix's keys and its resolution order; the check for
the row that matches everything.

**Violation.** A model chosen outside the matrix; a resolution that
picks a less specific row over a more specific one; a matrix that can be
published without the row that matches everything.

**Severity.** medium

**Check.** review

## MNY-13 The matrix is published by version, and a session keeps its own

**Principle.** The matrix is edited as a pending version and published.
A running session keeps the version it started with until it switches
explicitly.

**Source.** Models Are a Fleet Decision.

**Look for.** How the matrix is edited and published; which version a
running session resolves with.

**Violation.** A matrix edited in place; a running session that resolves
with the latest version without an explicit switch.

**Severity.** high

**Check.** review

## MNY-14 A model enters the matrix after its price

**Principle.** A model enters the matrix only after its price does.

**Source.** Models Are a Fleet Decision.

**Look for.** The check, when a version is published, that every fill
has a price in the price table.

**Violation.** A matrix version published with a fill that has no price,
or only a default price.

**Severity.** high

**Check.** review

## MNY-15 A benchmark qualifies a fill, and gates a matrix release

**Principle.** A model enters the matrix only after a benchmark run
passes for the model roles it will serve. Benchmarks never gate a code
change; they gate a matrix release.

**Source.** Models Are a Fleet Decision.

**Look for.** What a fill needs before it is published; where benchmarks
run as a gate.

**Violation.** A fill published for a model role with no passing
benchmark run for that role; a benchmark wired as a gate on a code
change.

**Severity.** medium

**Check.** review

## MNY-16 A tenant chooses only among qualified fills

**Principle.** By default a tenant never names a model. A tenant on its
own keys may override the fill for a model role, among qualified fills
from providers it holds keys for.

**Source.** Models Are a Fleet Decision.

**Look for.** Where a tenant can set a model or a fill; what an override
accepts.

**Violation.** A tenant setting that names a model; an override by a
tenant without its own keys; an override to an unqualified fill, or to
one from a provider the tenant holds no key for.

**Severity.** medium

**Check.** review

## MNY-17 Eligibility filters resolution, fallbacks included

**Principle.** A tenant that requires zero data retention, or a region,
is resolved only to fills that support it, fallbacks included.

**Source.** Models Are a Fleet Decision.

**Look for.** Where the tenant's retention and region requirements
filter the matrix; the fallback chain.

**Violation.** A fill or a fallback that does not support the tenant's
zero retention or its region.

**Severity.** medium

**Check.** review

## MNY-18 A retired model re-resolves at the next loop, with a step

**Principle.** When a provider retires a model, sessions on it
re-resolve at their next loop, with a `switched` step.

**Source.** Models Are a Fleet Decision.

**Look for.** What becomes of sessions on a retired model, and when.

**Violation.** A session moved off a retired model mid-loop, or without
a `switched` step; a session left on a retired model.

**Severity.** high

**Check.** review
