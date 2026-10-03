# Fleet

Group id: `fleet`. Covers The Agents a Platform Ships, Failure at Fleet
Scale, and Operations of `distro_gentic_spec.md`.

This group judges the agents a platform ships, what the fleet does when
things fail, and how the platform is operated: the shipped kinds and
the platform assistant, a provider outage at scale, the sweep and its
duties, operational skills, the dashboard, and the telemetry round trip.
It leaves the outage signal itself to `money`, each sweep duty's own rule
to the lens that states it (FLT-08 names them), and how an agent kind is
defined to the engine.

## FLT-01 A platform's agents are kinds of one loop

**Principle.** One loop, many kinds. A platform ships a few, each a
profile with its own powers: the engineer takes an objective to a
validated, reviewable change; analysis agents read what a run produced
and turn it into findings; a planner turns findings into tasks and
decides whether an existing session should continue or a new one should
start.

**Source.** The Agents a Platform Ships.

**Look for.** How each shipped agent is defined; whether any runs a loop
of its own.

**Violation.** A shipped agent with a loop of its own; a kind whose
powers its profile does not set.

**Severity.** medium

**Check.** review

## FLT-02 A validation session runs a delivery's checks with no agent

**Principle.** A validation session runs a delivery's checks with no
agent at all, on a fresh executor (a workspace nobody used, never the
agent's), on the same queue, and writes the same execution record.

**Source.** The Agents a Platform Ships.

**Look for.** How a validation session runs; the executor it runs on;
the queue it uses; the records it writes.

**Violation.** A validation session that makes a model call; one that
runs off the work queue, or writes records of another shape. (One run in
the agent's workspace or on a reused executor is EVD-06.)

**Severity.** medium

**Check.** review

## FLT-03 The assistant diagnoses with tools, drafts, and never applies

**Principle.** The platform assistant helps the people who set up and
run their part of the platform. It explains the product, citing a
corpus. It diagnoses live state with tools, never with guesses. It
drafts configuration, validates it against the tenant's real records,
and shows the difference from what is live; a person applies it. Its
authority is delegated, and it has no workspace, repository, or shell.

**Source.** The Agents a Platform Ships.

**Look for.** The assistant kind's tools and its authority mode; how a
draft becomes live configuration.

**Violation.** An assistant tool that applies configuration; an
assistant with a workspace, a repository, or a shell; an assistant with
steady authority.

**Severity.** high

**Check.** review

## FLT-04 The assistant hands engineering off, and nothing routes

**Principle.** The assistant hands engineering work to an engineer
session with a self-contained objective, then steps back. There is no
router between the assistant and the engineer: a person chooses by
choosing where to type.

**Source.** The Agents a Platform Ships.

**Look for.** How the assistant starts an engineer session, and what it
passes; any component that routes a person's message to one or the
other.

**Violation.** A hand-off that passes the assistant's conversation
instead of a self-contained objective; an assistant that keeps working
on the engineering task; a router that picks the assistant or the
engineer for a message.

**Severity.** medium

**Check.** review

## FLT-05 The assistant's corpus is the knowledge map's list for users

**Principle.** The assistant's corpus is what the guideline's knowledge
map lists for the tenant's users, so internal text never leaks by
default, and the words a customer reads and the words the team works
from are the same text.

**Source.** The Agents a Platform Ships.

**Look for.** Where the assistant's corpus is assembled, and what picks
its documents.

**Violation.** A corpus assembled from anything but the knowledge map's
list for the tenant's users; an internal document in the corpus by
default; a second copy of a text, written for the assistant.

**Severity.** medium

**Check.** review

## FLT-06 An outage parks its sessions at once, and they wake staggered

**Principle.** When a provider fails, its outage signal turns on and
every session that meets it parks within a second, naming the provider.
When the signal's retry time passes, the parked sessions are woken,
staggered.

**Source.** Failure at Fleet Scale.

**Look for.** What a session does when it meets an outage signal; how
the parked sessions are woken when the retry time passes.

**Violation.** A session that retries a provider under an outage signal
instead of parking; a park that does not name the provider; every
parked session woken at the same instant.

**Severity.** medium

**Check.** review

## FLT-07 Every cloud worker runs the sweep, and a beat is no trigger

**Principle.** Sessions die with their runners, and the platform notices
through the guideline's sweep, which every cloud worker runs; hosts, not
worker roles, never run it. A runner's beat is a signal, never a
trigger.

**Source.** Failure at Fleet Scale.

**Look for.** Which processes run the sweep; what a runner's beat
causes.

**Violation.** A host that runs the sweep; a cloud worker role that does
not; a recovery that a missed beat starts, rather than the sweep.

**Severity.** medium

**Check.** review

## FLT-08 The sweep carries the platform's duties

**Principle.** The platform adds its duties to the sweep: an expired
loop is requeued; an expired `exec` item follows the relay transport; a
workspace instance nobody claims is purged; a hold nobody settled
settles; an approval past its expiry is asked again; a session with a
pending input and no queued loop is woken; and expired content's keys
are revoked and expired shape purged.

**Source.** Failure at Fleet Scale.

**Look for.** The sweep's duties, and the query behind each.

**Violation.** A duty missing from the sweep, or run by a scheduler, a
runner's beat, or a host. (Each duty's own rule is its lens: FLT-09,
PLC-20, WSP-01, FLT-10, WAL-12.)

**Severity.** medium

**Check.** review

## FLT-09 A requeued loop takes a new writer epoch

**Principle.** A loop whose lease expired is requeued, and its next run
takes a new writer epoch.

**Source.** Failure at Fleet Scale.

**Look for.** The sweep's requeue of an expired loop; where the next run
takes its epoch.

**Violation.** A requeued loop whose next run keeps the old writer
epoch, or writes before it takes a new one.

**Severity.** high

**Check.** review

## FLT-10 A hold nobody settled settles unless the provider did not bill

**Principle.** A hold nobody settled settles at usage retrieved from the
provider, else at its full amount, and is released only when the
provider provably did not bill.

**Source.** Failure at Fleet Scale.

**Look for.** What the sweep does with an open hold nobody settled.

**Violation.** A hold released, or settled at zero, without proof that
the provider did not bill; a hold settled at an estimate when the usage
can be retrieved.

**Severity.** high

**Check.** review

## FLT-11 A repeating operator task is a skill, and two audits are required

**Principle.** The platform is operated the way the guideline operates
every system: each task that repeats is a skill a person runs with an
agent, and the boundary is the credential it holds. The scaffold ships
the platform's operational skills beside the guideline's own
(`ops-session-stuck`, `ops-host-idle`, `ops-integration-silent`,
`ops-provider-outage`, `audit-model-spend`), and makes two of the
guideline's optional audits required, `audit-provider-calls` and
`audit-credential-lifetimes`.

**Source.** Operations.

**Look for.** The scaffold's operational skills, and the credential each
holds; the audits the scaffold requires.

**Violation.** A repeating operator task with no skill, or a skill that
holds a wider credential than its role; one of the platform's
operational skills missing; `audit-provider-calls` or
`audit-credential-lifetimes` left optional.

**Severity.** medium

**Check.** review

## FLT-12 The dashboard's labels are bounded

**Principle.** The operator dashboard, declared as code, adds the
platform's signals, each with a bounded label: parks by reason and age,
loop lanes' depth by plan tier, hosts by pool, cache hit rates, and
spend by matrix version. Views of one tenant or one host are
operator-plane reads, never labels.

**Source.** Operations.

**Look for.** The dashboard's definition, and each signal's labels.

**Violation.** A dashboard built by hand; a signal labelled by tenant,
host, session, or any other unbounded value; one of the platform's
signals missing.

**Severity.** medium

**Check.** `distro-check` decides that no metric whose label names are a
literal or a module constant is labelled by a tenant, a host, a session,
a person, a request, a workspace, or a project; the rest is judged.

## FLT-13 One run's request id crosses the runner, the host, and its steps

**Principle.** The guideline's telemetry round trip follows one run's
request id across the runner, the host, and the steps it wrote.

**Source.** Operations.

**Look for.** How the request id travels from the runner to the host and
into the steps.

**Violation.** A relayed `exec` item or a step that does not carry the
run's request id; a host that mints its own.

**Severity.** medium

**Check.** review
