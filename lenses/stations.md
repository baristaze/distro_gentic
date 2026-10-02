# Stations

Group id: `stations`. Covers Stations of `distro_gentic_spec.md`.

Stations are optional. A platform without them skips this group; once it
adopts them, every lens here holds. This group judges the scarce, located
things work needs and cannot carry: the line a session waits in, the
lease and its fencing token, the daemon that fences it, and the guard
nearest the resource. It leaves the `station` work kind and its lane,
and the rule that a daemon opens every connection outward, to
`placement`; a station's secrets to `wall`; a validation session and the
sweep that frees an expired lease or clears a stale line entry to
`fleet`; and a park's shape to the engine.

## STN-01 A session waits for a station in a line, parked

**Principle.** An agent that cannot get a station never polls for it,
burning model calls while it waits. Stations of one kind form a pool,
and a request names a station or a pool with the capabilities it needs.
Each pool and each station has a line. A session that asks joins it,
sees its position and an estimate, and parks on the resource.

**Source.** Stations, The Line.

**Look for.** How a session asks for a station; the line, and the
position and estimate it reports; what the loop does while it waits.

**Violation.** A tool or a loop that asks a busy station again, or
sleeps and retries; a request that cannot name a pool by its
capabilities; a waiting session that is not parked on the resource, or
does not see its position.

**Severity.** medium

**Check.** review

## STN-02 A free station goes to the first matching request in line

**Principle.** When a station frees up, the control plane grants it to
the first matching request in line, and the grant wakes the session with
an event naming the station and its lease. A person who manages the
stations may reorder a line. A session that finishes or is cancelled
leaves every line it stood in, and a session that no longer waits is
never granted anything.

**Source.** Stations, The Line.

**Look for.** The grant path when a station frees; the wake event and
what it names; who may reorder a line; what finishing, cancelling, or no
longer waiting does to a session's places in line.

**Violation.** A grant out of line order that no person who manages the
stations made; a grant that does not wake the session, or omits the
station or the lease; a finished, cancelled, or no longer waiting
session left in a line, or granted a station.

**Severity.** medium

**Check.** review

## STN-03 A station job's approvals come before the line

**Principle.** Approvals a station job needs are asked before the
session joins the line, bound to the candidate, the procedure, and the
pool, and kept while the session holds its place, so a lease never waits
on a person.

**Source.** Stations, The Line.

**Look for.** When a station job's approvals are asked, and what each
binds; whether a held lease can wait for an approval.

**Violation.** An approval asked after the grant, or while the lease is
held; an approval not bound to the candidate, the procedure, and the
pool; an approval dropped while the session still holds its place.

**Severity.** medium

**Check.** review

## STN-04 A lease is one station's, with a token that grows every grant

**Principle.** A grant is a lease: a time-limited, renewable right to one
station, with a fencing token that grows with every grant. A station
lease is not a work lease.

**Source.** Stations, Leases.

**Look for.** The lease record: its station, its expiry, its renewal, and
its fencing token; how the token is made at each grant.

**Violation.** A lease with no expiry, or over more than one station; a
token that is reused, random, or not greater than every earlier grant's;
a work item's lease used as the station's lease.

**Severity.** high

**Check.** review

## STN-05 The daemon renews a lease, and a parked one lasts its hold time

**Principle.** During a station job the daemon renews the lease as the
executor. While its session is parked, the lease survives only for a
declared hold time.

**Source.** Stations, Leases.

**Look for.** Who renews a station lease during a job, and as whom; what
a parked session's lease does, and where its hold time is declared.

**Violation.** A lease renewed by the runner or the session instead of
the daemon; a parked session that keeps its lease past its hold time, or
whose hold time is never declared.

**Severity.** medium

**Check.** review

## STN-06 The daemon is the fence

**Principle.** The daemon is the fence. It keeps the highest token it
has seen for each station and checks it on every command, and before it
accepts a higher token it stops the station and restores its baseline.

**Source.** Stations, Leases.

**Look for.** The daemon's token for each station, and every command
path; what the daemon does when a higher token arrives.

**Violation.** A command the daemon runs without comparing its token
with the highest seen; a command with a lower token accepted; a higher
token accepted before the station is stopped and its baseline restored.

**Severity.** high

**Check.** review

## STN-07 One live lease per station

**Principle.** The lease store grants with a conditional write that
fails while a live lease exists, and grants again only after an expiry
plus a margin for clock skew. The daemon times expiry on a monotonic
clock.

**Source.** Stations, Leases.

**Look for.** The lease store's grant write and its condition; the margin
after expiry; the clock the daemon times expiry by.

**Violation.** A grant that reads and then writes, or writes with no
condition; a grant again at expiry with no margin for skew; a daemon
that times expiry by the wall clock.

**Severity.** high

**Check.** review

## STN-08 A revoked lease ends in the station's controlled stop

**Principle.** A person who manages the stations may revoke a lease. The
holding session is told, and the station takes its declared controlled
stop.

**Source.** Stations, Leases.

**Look for.** The revoke path, who may take it, and what reaches the
session and the station.

**Violation.** A revoke the holding session is not told of; a revoked
station that stops some other way than its declared controlled stop, or
keeps running the job.

**Severity.** high

**Check.** review

## STN-09 The daemon is a least-privilege client that grants itself nothing

**Principle.** A station is reached through a station daemon on its
host, inside the customer's wall: a least-privilege client of the
gateway that pulls station work, fences leases, runs the station's
adapter, and streams what the station sees. It grants itself nothing.

**Source.** Stations, The Station Daemon.

**Look for.** The daemon's credential and its permissions; every path by
which the daemon comes to hold a lease or a work item.

**Violation.** A daemon that creates or extends its own lease, or runs
station work no grant gave it; a daemon credential with permissions
beyond its station work, its leases, and its streams. (A connection
opened into the wall is PLC-10.)

**Severity.** high

**Check.** review

## STN-10 Device access is declared, and a job reaches it via the adapter

**Principle.** Each station declares the device access it needs, and that
declaration becomes a reviewable piece of the host's service
configuration, line by line. Code a station job runs is isolated from
the daemon, and it reaches the station only through the adapter.

**Source.** Stations, The Station Daemon.

**Look for.** Where a station's device access is declared, and how it
reaches the host's service configuration; how a station job's code runs
beside the daemon.

**Violation.** Device access granted wholesale, or outside the declared
configuration; a job's code that runs in the daemon's process or as its
user, or that opens a device directly.

**Severity.** high

**Check.** review

## STN-11 A station's limits are the customer's, and nothing raises them

**Principle.** A station's limits are the customer's own numbers, kept
and enforced on the station's host. A refused command is recorded as
evidence. Nothing the platform sends, a policy, an approval, or a
command, can raise a limit.

**Source.** Stations, The Guard Nearest the Resource.

**Look for.** Where a station's limits are stored and checked; every
message from the platform the daemon applies; what is recorded when a
command is refused.

**Violation.** A limit stored in, sent by, or changed from the platform;
a policy, an approval, or a command that raises a limit; a refused
command with no evidence record.

**Severity.** high

**Check.** review

## STN-12 Safety stops are local, and outlive the control plane

**Principle.** Safety stops live at the station, where they keep working
when the control plane is slow or unreachable. A daemon that loses the
control plane lets the current job run to its lease's expiry and accepts
no new station job. The daemon holds this logic itself: it is the
platform's recorded deviation from the guideline's dumb apps, because
the guard nearest the resource must work when the server is slow or
gone.

**Source.** Stations, The Guard Nearest the Resource; Deviations from the
Guideline.

**Look for.** Where safety stops run, and what they depend on; what the
daemon does when it loses the control plane, for the current job and for
a new one.

**Violation.** A safety stop that waits on a call to the control plane;
a daemon cut off from the control plane that runs its current job past
the lease's expiry, or accepts a new station job.

**Severity.** high

**Check.** review
