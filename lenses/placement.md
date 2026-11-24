# Placement

Group id: `placement`. Covers Sessions Are Work, Agent Session Runners, and
Placement and Workspace Hosts of `distro_gentic_spec.md`, and the rule
At a Glance states for every connection that crosses a customer's wall.

This group judges where each part of a session runs and how its work
reaches it: the kinds of work and their lanes, the session runner that
hosts the brain, placement, the workspace host and what it holds, the
exec relay transport that carries a tool call into a customer's wall,
the cloud pool's VM per session, and a person's own client that serves
their session's local workspace. It leaves a workspace's
isolation and egress to `workspaces`, a person's commands on a workspace
to `watch`, the four identities and how a secret is resolved to `wall`,
and the sweep's duties to `agent-fleet`.

## PLC-01 A session becomes work of a kind, claimed where it can run

**Principle.** A session always lives in the control plane, whatever
machine runs its commands. To make progress it becomes a row of the
guideline's work queue, of one kind: `loop`, `exec`, `workspace`, or the
platform's own. Each kind runs where its environment is, claimed from
its lane, and a lane is the guideline's work-item lane, so every kind is
one queue with one shape. A runner claims from the queue directly; a
host outside the cloud claims through the gateway, and the control plane
claims the row on its behalf; a VM of the cloud pool is such a host.
Only a workspace on the runner's own machine needs no item: the runner
reaches it by the direct transport.

**Source.** Sessions Are Work, Kinds of Work.

**Look for.** The work kinds and the lane each is claimed from; the
claim path of a runner, and of a host outside the cloud; how a tool call
reaches a VM of the cloud pool, and a workspace on the runner's own
machine.

**Violation.** A second queue, or a work row of the platform's own shape
beside the guideline's; a kind claimed from a lane other than the one
where its environment is; a tool call to a VM of the cloud pool sent by
any way but an `exec` item, or an `exec` item made for a tool call to a
workspace on the runner's own machine. (A host that reaches the queue's
storage itself holds a
database credential, which is PLC-16.)

**Severity.** medium

**Check.** review

## PLC-02 Loops share by plan tier, and the claim holds each tenant to its cap

**Principle.** Loops are long and expensive, so the platform shares them
by the guideline's means. Loop work runs in a lane per plan tier, and a
tenant whose bulk work still crowds its neighbours gets a lane of its
own. Each tier's share is its lane's cap, the most loops one tenant
holds claimed there, with the platform's default for a tier that names
none. An operator can give one tenant a cap of its own on its lane, in
place of its tier's share. The guideline's claim holds both: a tenant at
its cap is passed over, and its loops wait unwritten and spend no
attempt. The claim order within a lane stays the guideline's.

**Source.** Sessions Are Work, Fair Share.

**Look for.** The loop lanes and how a session's plan tier picks one;
the cap a runner's lane passes to the claim, and where each tier's share
is set; where an operator sets a tenant's own cap; what a loop of a
tenant at its cap does; the claim order within a lane.

**Violation.** One loop lane for every tier; a limit of the platform's
own beside the guideline's caps, or one checked when a session is
created or a loop is enqueued instead of at the claim; a claimed loop
handed back over its tenant's share, which spends a claim and a write;
a tenant's own cap kept anywhere but the work queue's; a claim order of
the platform's own within a lane.

**Severity.** medium

**Check.** review

## PLC-03 The brain runs in the platform's cloud, always

**Principle.** A session runner is a worker role that claims `loop` work
and hosts the engine while it runs a session's loop. It runs in the
platform's cloud, always. Model keys, the history, and the budget gate
never leave it, and a runner never runs inside the sandbox it drives.

**Source.** Agent Session Runners.

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

**Source.** Agent Session Runners.

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

**Source.** Agent Session Runners.

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

**Source.** Agent Session Runners.

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

**Principle.** A runner chooses the transport by where the session's
workspace is: an exec relay transport to a host, inside a customer's
wall or on a VM of the cloud pool, or a direct transport to a workspace
on the runner's own machine, such as a container beside it. The engine
sees one transport interface either way.

**Source.** Agent Session Runners.

**Look for.** Where the runner picks a transport; any code in the engine
or in a tool that branches on where the workspace is.

**Violation.** A transport chosen by anything but where the session's
workspace is; the engine or a tool that branches on cloud or wall, or
reaches a host other than through the transport interface. (A tool that
reaches past the transport is the engine's TOL-13, which grades it
high.)

**Severity.** high

**Check.** review

## PLC-08 A pinned session waits, and never moves unasked

**Principle.** Placement is part of a session: the cloud pool, or a
customer's host pool (one or more hosts inside their wall that share
labels), in a region. A session pinned to a host pool waits, visibly,
while no host in the pool is online. It never moves to the cloud unless
a principal changes its placement, because a team pins a machine for a
reason. A local session is pinned to its own pool of one, and waits so
while no client of its person serves it.

**Source.** Placement and Workspace Hosts, Placement.

**Look for.** The placement a session carries; what happens when no host
in its pool is online; every path that changes a session's placement.

**Violation.** A session with no placement, or one placed anew at each
loop; a pinned session that falls back to the cloud or another pool when
its hosts are offline, a local one included while no client serves it; a
wait the session's status does not show; a placement changed by anything
but a principal, or by the session's start for a local one.

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
connection that crosses a customer's wall is opened from inside it.

**Source.** At a Glance; Placement and Workspace Hosts, Workspace Hosts;
The Exec Relay Transport.

**Look for.** How a host connects to the platform; any listener or
inbound port it opens; any platform code that dials an address inside a
customer's wall.

**Violation.** A platform service that opens a connection to a host
inside a customer's wall: a callback URL, an inbound port, a push to its
address; a host inside a customer's wall deployed as a process of the
platform's deployment, or reaching the platform by anything but the
gateway.

**Severity.** high

**Check.** `distro-check` decides that a host's modules import nothing of
the platform but their own app and the client of the gateway; the rest
is judged.

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

## PLC-12 Exec work is a versioned public type

**Principle.** `exec` work is a public wire type, versioned like any
other. A host states its version at every claim, and one below the
supported floor is refused, since a customer upgrades on its own
schedule.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Versioned
work).

**Look for.** The wire type of `exec` work and its versions; the version
a claim carries; the floor check.

**Violation.** An internal type sent as `exec` work; a claim with no
version; a host below the floor handed work; a breaking change to a wire
type without a new version.

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
cannot raise: the agent projects it serves, its minimum isolation, its
egress, the paths it lets a result read, whether it accepts people's
commands, and the MCP servers it starts, each named whole. A refusal
names the ceiling that refused. A compromised control plane still cannot
widen what a host does.

**Source.** Placement and Workspace Hosts, Workspace Hosts (Owner's
ceilings); Deviations from the Guideline.

**Look for.** Where the owner's ceilings are kept and checked on the
host; what a refusal says; every message from the control plane that
could change one.

**Violation.** A ceiling kept or checked only in the control plane; a
work item, a policy, or a setting from the control plane that serves
another agent project, lowers the minimum isolation, widens egress or
the readable paths, turns on people's commands, or names a program, an
argument, or a variable for a server the host starts; a refusal that
does not name its ceiling.

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

**Check.** `distro-check` decides that no host module names a variable
the cloud's settings read a secret, a key, a token, a password, or a
database setting from, a variable of its secret store, or a model
provider's key; the rest is judged.

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

**Source.** Placement and Workspace Hosts, The Exec Relay Transport.

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

**Source.** Placement and Workspace Hosts, The Exec Relay Transport.

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

**Source.** Placement and Workspace Hosts, The Exec Relay Transport.

**Look for.** What a resumed run does with an `exec` item that already
exists; what happens to an item whose lease expires, by its effect.

**Violation.** A resume that makes a second item or runs the command
again; an `unsafe` item requeued or retried; a requeued item sent to a
host other than the one that holds its workspace.

**Severity.** high

**Check.** review

## PLC-21 A cloud VM is its session's alone, holds nothing, and goes

**Principle.** A cloud session whose workspace is a VM runs on a VM
of its own, whose host program pulls its work through the exec relay.
Its host trades a one-use key for a credential of the session's own
pool, and is handed that session's work alone. It holds no database
credential, model key, history, or cloud role, and its key and
credential never reach its disk. Its egress and lookups are closed
outside its guest. A session kept by snapshots keeps its directory
sealed under its key in the object store, 30 days by default past its
last activity, and no disk is imaged. A VM with no host stops; every
path that starts a VM lets it go.

**Source.** Placement and Workspace Hosts, The Cloud Pool.

**Look for.** How a VM's host gets its credential and what its
claims are held to; what a VM's image, its settings, its seed, and
its role hold; the network rules a VM starts in, and the names its
network resolves; what a run's end keeps of a VM, where, and under
whose key, and what the pool's role
may copy of a disk; what a restore starts its VM from, and what it
lets go when it fails; each path that starts a VM and the one that
lets it go, the sweep's among them; what a VM with no host to work
for comes to; what removes a session's archives, and when.

**Violation.** A VM's host enrolled with a tenant's token, or handed
another session's work; a database credential, a model key, a platform
secret, or a cloud role in a VM; a key or a live credential on a
disk; egress closed by a rule inside the guest, or open to more than
the gateway and the session's egress; a pool's network that resolves a
name a closed VM does not need, lets through a lookup its firewall
cannot judge, or runs the platform's other services; the platform
calling into a VM;
an image or a volume snapshot of a VM's disk, made by the pool or
allowed by its role; a session's files kept outside its key's seal, or
sent before their size was checked; a failed archive whose parts
remain, or a failed restore that changes what is kept or leaves its VM
half-restored; a VM that nothing lets go, warm or bound; a VM that runs
with no host; a disk a live session's VM ran on destroyed by the
sweep; a session's archives kept past their bound after its last
activity, or removed while it is active.

**Severity.** high

**Check.** review

## PLC-22 A file or an output crosses as a sealed object, never in an item

**Principle.** No file and no output rides in an `exec` item or its
result. Each crosses the store as an object, by URLs signed for it
alone: a file a write hands its host, a file a read uploads, and what a
command printed. The item names each object, its size, and its digest,
and the result names what its host uploaded the same way. An object is
sealed under a key of its own, which the item keeps under the session's
key. Nothing of a file reaches a workspace, or the runner, until it
matches its digest. A file leaves the store once its item settles; an
output goes with the item.

**Source.** Placement and Workspace Hosts, The Exec Relay Transport.

**Look for.** What an item's detail and a host's result carry; what a
host is handed to read or write an object, and for how long; where an
object's digest is checked before its bytes are used; what removes an
object when its item settles or its session is purged.

**Violation.** A file's or an output's bytes in an item, a result, or any
request to the API; an object sealed under the session's key itself, or
under none, so a host could open another object; a URL signed for more
than one object, or with no expiry; bytes written into a workspace, or
handed to the runner, before their digest matched; a file left in the
store after its item settled. (A holder's call that carries bulk bytes
is the guideline's NET-37.)

**Severity.** high

**Check.** review

## PLC-23 The cloud pool holds its maxima, and no claim races its sweep

**Principle.** The cloud pool holds at most a maximum of VMs at once,
and one tenant at most its own. A VM counts from its start or claim
until it is let go. Warm VMs stand below the maximum, and at it yield to
a claim that cannot take one. The limits are operator records, read at
every claim and refill, each write audited with its writer and values.
A claim past a maximum starts no VM; its session waits, told no count or
other tenant's use. A VM's host gets its session's work only once it
holds the workspace. The sweep takes a warm VM's record under the
claim's lock before destroying it, and lets go of a dead VM.

**Source.** Placement and Workspace Hosts, The Cloud Pool.

**Look for.** Where a claim and a refill count the VMs held, and the
lock they count under; where the limits are read, and whether a deploy
setting or a cache stands in for them; what a write of a limit
records, and in whose stream; what a park past a maximum says; the
order of a destroy and its record's delete on each path that lets a
warm VM go; what a claim that cannot take a warm VM does at the
maximum; how the sweep finds a VM that died.

**Violation.** A VM started, or a warm one claimed, past a maximum,
or counted outside the lock, so two claims pass it together; a limit
read from a deploy setting, or held in memory past a write; a write
of a limit with no audit event, or the pool's own limits in a tenant's
stream; a park that names a count, the pool's size, or another
tenant's use; a warm VM destroyed before its record is taken, so a
claim binds a VM being destroyed; a VM gone from the backend whose
record still holds a place; an idle warm VM that keeps a claim that
cannot take it waiting at the maximum; a host handed its session's work
before it holds the workspace.

**Severity.** high

**Check.** review

## PLC-24 A person's own client serves their local session, and follows others

**Principle.** A session's workspace is local when the person who
started it serves it from their own machine. The session is pinned to a
pool of one of its own. Its person's client trades a one-use key, which
the platform issues that person alone, for a host's credential of that
pool, never the person's own, and runs the host program's claim loop,
held to the machine's ceilings. It serves the session, its sub-agents,
and their checks' instances, and no other session. One client serves the
session at a time, and a client ends its host as it stops. A client
attached to a session whose workspace a VM, a host, or another person's
client holds follows it and serves nothing.

**Source.** Placement and Workspace Hosts, Placement; Placement and
Workspace Hosts, Workspace Hosts (A person's own client).

**Look for.** How a local session is pinned, and to which pool; what
issues a client key, to whom, for how long, and how many times it is
traded; what a client's host carries in its identity and what its claims
are held to; what ends an earlier client; what a client does when told
the session is held elsewhere.

**Violation.** A client that serves on the person's own credential; a key
that enrolls twice, outlives its few minutes, or is issued for another
person's session or one that is not local; a client's host handed the
work of a session outside its session's tree, or one that fails a
sub-agent's work or an instance its checks ask for; a local session's
pool shared with the cloud pool's, a tenant's, or another session's; two
clients serving one session; a client that serves a session whose
workspace a VM or a host holds; a client that claims through a loop of
its own beside the host program's, so a ceiling holds on one and not the
other.

**Severity.** high

**Check.** review

## PLC-25 A cloud VM is its kind's size, recycled between runs, its boot timed

**Principle.** A kind asks its VM's size by name, `s` when it asks none,
and the deployment maps each name it allows onto a machine type; the
pool's cloud role launches no other type and moves no VM to one. An
unmapped size, or an ask of CPUs or memory, is refused for good, with
its cause, before the loop's first model call. Warm VMs are the default
size. A VM past its maximum age goes between runs once its work is kept;
a warm one, at the sweep. A cold start times its boot, a warm claim
none. Each claim counts once, by how it got its VM, and times its first
command; a restore is timed by size class.

**Source.** Placement and Workspace Hosts, The Cloud Pool.

**Look for.** How a spec's size becomes the machine type a start names,
and what a warm claim reads of it; what the pool's cloud role allows a
start, and a change of an attribute, to be; where a VM's age is read and
what has run, and what is kept, when it goes; where a boot is observed,
and what tells a cold start from a warm claim and a start again; where a
claim is counted and what tells a claim asked again from another, and
where its first command and a restore are timed.

**Violation.** A VM of a type the deployment never mapped, or of
another size than its spec asked, a raw CPU or memory ask met, or a
refusal after the loop's first model call or a VM's start; a role that
launches, or moves a VM to, any type; a VM let go for its age under a
running loop, or before its run's work was kept; a VM that lives across
runs with no maximum age; a boot
recorded for a warm claim or a start again, or a cold start recorded
twice or not at all; a claim counted twice, under two sources, or not at
all; a claim's wait recorded for each command, or a restore's never.

**Severity.** high

**Check.** review
