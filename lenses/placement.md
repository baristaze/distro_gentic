# Placement

Group id: `placement`. Covers Sessions Are Work, Session Runners, and
Placement and Workspace Hosts of `distro_gentic_spec.md`, and the rule
At a Glance states for every connection that crosses a customer's wall.

This group judges where each part of a session runs and how its work
reaches it: the kinds of work and their lanes, the session runner that
hosts the brain, placement, the workspace host and what it holds, and
the relay transport that carries a tool call into a customer's wall. It
leaves a workspace's isolation and egress to `workspaces`, station work
to `stations`, a person's commands on a workspace to `watch`, the four
identities and how a secret is resolved to `wall`, and the sweep's
duties to `fleet`.

## PLC-01 A session becomes work of a kind, claimed where it can run

**Principle.** A session always lives in the control plane, whatever
machine runs its commands. To make progress it becomes a row of the
guideline's work queue, of one kind: `loop`, `exec`, `workspace`,
`station`, or the platform's own. Each kind runs where its environment
is, claimed from its lane, and a lane is the guideline's work-item lane,
so every kind is one queue with one shape. A runner claims from the
queue directly; a host or a daemon outside the cloud claims through the
gateway, and the control plane claims the row on its behalf. A tool call
to a cloud workspace needs no item: the runner reaches it by the direct
transport.

**Source.** Sessions Are Work, Kinds of Work.

**Look for.** The work kinds and the lane each is claimed from; the
claim path of a runner, and of a host or a daemon outside the cloud; how
a tool call reaches a cloud workspace.

**Violation.** A second queue, or a work row of the platform's own shape
beside the guideline's; a kind claimed from a lane other than the one
where its environment is; an `exec` item made for a tool call to a cloud
workspace. (A host that reaches the queue's storage itself holds a
database credential, which is PLC-16.)

**Severity.** medium

**Check.** review

## PLC-02 Loops share by plan tier, and a tenant's limit guards the claim

**Principle.** Loops are long and expensive, so the platform shares them
by the guideline's means. Loop work runs in a lane per plan tier, and a
tenant whose bulk work still crowds its neighbours gets a lane of its
own. Each tenant has a concurrency limit, enforced as a guard at the
claim: a claimed loop over its tenant's limit goes back to its lane with
a delay and spends no attempt. The claim order within a lane stays the
guideline's.

**Source.** Sessions Are Work, Fair Share.

**Look for.** The loop lanes and how a session's plan tier picks one;
where a tenant's concurrency limit is checked; what a claimed loop over
the limit does; the claim order within a lane.

**Violation.** One loop lane for every tier; a concurrency limit checked
when a session is created or a loop is enqueued, instead of at the
claim; a loop over its limit that fails, spends an attempt, or returns
with no delay; a claim order of the platform's own within a lane.

**Severity.** medium

**Check.** review

## PLC-03 The brain runs in the platform's cloud, always

**Principle.** A session runner is a worker role that claims `loop` work
and hosts the engine while it runs a session's loop. It runs in the
platform's cloud, always. Model keys, the history, and the budget gate
never leave it, and a runner never runs inside the sandbox it drives.

**Source.** Session Runners.

**Look for.** Where the session runner is deployed and which process
hosts the engine; every path that sends a model key, the history, or the
budget gate's state to a host; whether a runner ever starts inside a
workspace.

**Violation.** The engine's loop run on a workspace host or inside a
workspace, in the cloud or in a customer's wall; a model key, the
history, or the budget gate shipped to or held by a host; a model call
made from a host.

**Severity.** high

**Check.** review

## PLC-04 Agent kinds live in the platform

**Principle.** Agent kinds live in the platform. They are defined,
versioned, and policy-checked there; no host carries one, and no
customer install runs its own.

**Source.** Session Runners.

**Look for.** Where an agent kind is defined and versioned, and where its
policy is checked; what a host's install ships and what it can load.

**Violation.** A kind's prompts, tools, or policy shipped to a host or
read from a host's configuration; a customer install that defines,
loads, or runs an agent kind of its own; a kind run without its version
or its policy check.

**Severity.** high

**Check.** review

## PLC-05 Any runner resumes any session

**Principle.** A runner holds nothing that cannot be rebuilt from
storage, so any runner resumes any session. A session's first run and
its second, a week later, rarely share a machine.

**Source.** Session Runners.

**Look for.** What a runner keeps in memory or on disk between runs;
whether a session's loop is routed to a particular runner.

**Violation.** State a resume needs, held only in a runner's memory or on
its disk; a session pinned to one runner, or a resume that fails on
another.

**Severity.** medium

**Check.** review

## PLC-06 A lost claim stops a runner's writes

**Principle.** A runner holds its lease as every worker does, and the
engine adds the writer epoch, which refuses a stale run's steps and
commands. A lost claim stops a runner's writes, whatever its clock says.

**Source.** Session Runners.

**Look for.** The runner's lease and its renewal; where a run takes its
writer epoch; every write and command a runner sends, and whether it
carries the epoch.

**Violation.** A runner that keeps writing after its lease is lost
because its own clock says the lease is live; a step or a command, a
relayed one included, sent without the writer epoch; a stale run's write
accepted.

**Severity.** high

**Check.** review

## PLC-07 A runner picks the transport by placement, behind one interface

**Principle.** A runner chooses the transport by the session's
placement: a direct transport to a cloud workspace, or a relay transport
to a host inside a customer's wall. The engine sees one transport
interface either way.

**Source.** Session Runners.

**Look for.** Where the runner picks a transport; any code in the engine
or in a tool that branches on where the workspace is.

**Violation.** A transport chosen by anything but the session's
placement; the engine or a tool that branches on cloud or wall, or
reaches a host other than through the transport interface.

**Severity.** medium

**Check.** review

## PLC-08 A pinned session waits, and never moves unasked

**Principle.** Placement is part of a session: the cloud pool, or a
customer's host pool (one or more hosts inside their wall that share
labels), in a region. A session pinned to a host pool waits, visibly,
while no host in the pool is online. It never moves to the cloud unless
a principal changes its placement, because a team pins a machine for a
reason.

**Source.** Placement and Workspace Hosts, Placement.

**Look for.** The placement a session carries; what happens when no host
in its pool is online; every path that changes a session's placement.

**Violation.** A session with no placement, or one placed anew at each
loop; a pinned session that falls back to the cloud or another pool when
its hosts are offline; a wait the session's status does not show; a
placement changed by anything but a principal.

**Severity.** medium

**Check.** review

## PLC-09 Placement keeps the work inside, never what the model reads

**Principle.** Placement keeps the checkout, the builds, the devices,
and the secrets inside the wall, never the content the model reads.
Every tool result, source code included, is stored in the platform's
history and sent to the model provider. A tenant that must keep some
content inside declares read deny-lists, which its hosts enforce before
a result leaves, and resolves only to fills eligible for its policy.

**Source.** Placement and Workspace Hosts, Placement.

**Look for.** Where a host applies the tenant's read deny-lists to a tool
result; what a surface or a document says placement keeps from the
model; how a tenant with deny-lists resolves its fills.

**Violation.** A deny-list applied in the cloud after the result
arrived, or skipped on some path (a file read, a command's output, a
stream part); a promise that a pinned placement keeps source code from
the model provider. (A fill outside the tenant's eligibility is MNY-17.)

**Severity.** medium

**Check.** review

## PLC-10 Hosts pull, and the platform never calls into a wall

**Principle.** A workspace host outside the cloud is a client of the
gateway, like the CLI, never a process of the platform's deployment. It
opens every connection outward; the platform never calls in. Every
connection that crosses a customer's wall is opened from inside it, a
station daemon's included.

**Source.** At a Glance; Placement and Workspace Hosts, Workspace Hosts;
The Relay Transport.

**Look for.** How a host and a daemon connect to the platform; any
listener or inbound port they open; any platform code that dials an
address inside a customer's wall.

**Violation.** A platform service that opens a connection to a host or a
daemon: a callback URL, an inbound port, a push to the host's address; a
host or a daemon deployed as a process of the platform's deployment, or
reaching the platform by anything but the gateway.

**Severity.** high

**Check.** review

## PLC-11 A host has a credential of its own

**Principle.** A host enrolls once with its organization's enrollment
token and receives a short-lived, rotating credential of a kind and
prefix of its own. That credential is the executor identity.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Its own
credential).

**Look for.** The enrollment path and what it issues; the credential's
kind, prefix, lifetime, and rotation; the identity a host's calls carry.

**Violation.** A host that calls with a person's token, a service
principal's, or the enrollment token itself; a host credential that
never expires or never rotates; a kind or a prefix it shares with
another credential. (An executor taken for a principal is WAL-01.)

**Severity.** high

**Check.** review

## PLC-12 Exec and station work are versioned public types

**Principle.** `exec` and `station` work are public wire types, versioned
like any other. A host states its version at every claim, and one below
the supported floor is refused, since a customer upgrades on its own
schedule.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Versioned
work).

**Look for.** The wire types of `exec` and `station` work and their
versions; the version a claim carries; the floor check.

**Violation.** An internal type sent as `exec` or `station` work; a claim
with no version; a host below the floor handed work; a breaking change
to a wire type without a new version.

**Severity.** medium

**Check.** review

## PLC-13 A host advertises only what it probed

**Principle.** At startup a host checks that it reaches what it needs
(its trust store, its proxy, the platform, a sane clock), so a
misconfigured host fails at startup, never mid-session. It advertises
its operating system and shell, its capabilities, and only the isolation
modes it probed, because an overclaimed mode silently weakens the
sandbox of every session that trusts it.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Probing).

**Look for.** The host's startup probe and what it checks; what the host
advertises, and where each advertised value comes from.

**Violation.** A host that starts without checking its trust store, its
proxy, the platform, or its clock; an isolation mode or a capability
advertised from configuration or a default rather than from a probe that
passed.

**Severity.** high

**Check.** review

## PLC-14 A host is handed only the work pinned to its pool

**Principle.** A host is handed only the work pinned to its pool,
filtered by its identity, never by what it asks for.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Pinned
claims).

**Look for.** The claim a host makes and the filter the control plane
applies to it.

**Violation.** A claim filtered by a pool, a tenant, or a label the host
names in its request; a host handed work pinned to another pool.

**Severity.** high

**Check.** review

## PLC-15 A host holds its owner's ceilings

**Principle.** A host enforces limits its owner sets and the platform
cannot raise: the projects it serves, its minimum isolation, its egress,
the paths it lets a result read, and whether it accepts people's
commands. A compromised control plane still cannot widen what a host
does.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Owner's
ceilings).

**Look for.** Where the owner's ceilings are kept and checked on the
host; every message from the control plane that could change one.

**Violation.** A ceiling kept or checked in the control plane; a work
item, a policy, or a setting from the control plane that serves another
project, lowers the minimum isolation, widens egress or the readable
paths, or turns on people's commands.

**Severity.** high

**Check.** review

## PLC-16 A host holds no database credential, model key, or history

**Principle.** A host holds no database credential, no model key, and
no history: only its own credential, its local secret store (keyed by
tenant first, as every secret is), and the files of its workspaces. The
one credential the platform issues it is a push token minted per
session, short-lived and scoped to the session's branch, never the
integration's own credential.

**Source.** Placement and Workspace Hosts, Workspace Hosts (What it
holds).

**Look for.** Everything a host is configured with, sent, or caches; the
push token's minting, lifetime, and scope; how the local secret store is
keyed.

**Violation.** A database credential, a model key, the history, or an
integration's own credential on a host; a push token that outlives its
session or reaches beyond its branch; a local store keyed by anything
before the tenant.

**Severity.** high

**Check.** review

## PLC-17 A workspace's exec work goes to the host that holds it

**Principle.** A workspace lives on the host that prepared it, so its
`exec` work goes to that host's lane. A host that is lost takes its
workspaces with it, since a workspace is a cache, and the next loop
prepares another in the same pool.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Workspace
binding).

**Look for.** How an `exec` item is routed to a lane; what the next loop
does when the host holding its workspace is lost.

**Violation.** A workspace's `exec` work sent to the pool's lane or to
another host; a session stuck on a lost host's workspace instead of
preparing another in the same pool; a workspace prepared again in a
different pool.

**Severity.** medium

**Check.** review

## PLC-18 A relayed tool call is exec work keyed by its request

**Principle.** A tool call into a customer's wall travels as `exec`
work. The item's id derives from the tool request's idempotency key, and
it carries the command or file operation, the tool's effect, the
deadline, the writer epoch, and the session's isolation spec. The host
claims it under a lease, runs it through its local transport, streams
output parts back, and pushes the result, which the control plane stores
under the key. The runner writes the `tool_response` from that result.

**Source.** Placement and Workspace Hosts, The Relay Transport.

**Look for.** How an `exec` item's id is made and what the item carries;
the host's claim, run, and push; where the result is stored, and what
the runner writes the response from.

**Violation.** An item id that is random or not derived from the
idempotency key; an item without its effect, deadline, writer epoch, or
isolation spec; a `tool_response` written from anything but the result
stored under the key.

**Severity.** high

**Check.** review

## PLC-19 A control stream starts and stops a command at once

**Principle.** A host holds one long-lived outbound stream to the
control plane, which carries wake-ups, cancels, interrupts, deadline
cuts, and lease revocations, so a command starts at once and stops at
once. The work row stays the record. A person's terminal is a recorded
terminal session over the same stream, never a remote desktop.

**Source.** Placement and Workspace Hosts, The Relay Transport.

**Look for.** The host's control stream and what it carries; whether the
work row or the stream holds the record; how a person's terminal reaches
a host.

**Violation.** A host that polls for cancels or interrupts, or learns of
one only at its next claim; state that lives only on the stream and not
on the work row; a person's terminal over a remote desktop or any
channel that is not recorded. (A person's commands and their record are
WAT-06.)

**Severity.** medium

**Check.** review

## PLC-20 An unsafe call is never repeated

**Principle.** Because an item is keyed, a run that resumes after a
crash attaches to the first execution, or reads its stored result, and
never starts a second one. An item whose lease expires is requeued only
when its effect is `read_only` or `idempotent`, and only to the host
that holds its workspace; an `unsafe` one completes `interrupted`,
outcome unknown.

**Source.** Placement and Workspace Hosts, The Relay Transport.

**Look for.** What a resumed run does with an `exec` item that already
exists; what happens to an item whose lease expires, by its effect.

**Violation.** A resume that makes a second item or runs the command
again; an `unsafe` item requeued or retried; a requeued item sent to a
host other than the one that holds its workspace.

**Severity.** high

**Check.** review
